from django.contrib import messages
from django.db import connection, transaction
from django.shortcuts import render, redirect
from django.conf import settings
from media.upload.ai.predict import predict_flower

import os
import smtplib
from email.mime.text import MIMEText


def get_user_role(user):
    if not user.is_authenticated:
        return None

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM auth_user WHERE id = %s", [user.id])
        row = cursor.fetchone()

    return row[0] if row else None


def get_or_create_cart(user_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id
            FROM carts
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT 1
        """, [user_id])
        row = cursor.fetchone()

        if row:
            return row[0]

        cursor.execute("""
            INSERT INTO carts (user_id)
            VALUES (%s)
            RETURNING id
        """, [user_id])
        new_row = cursor.fetchone()
        return new_row[0]


def save_uploaded_file(uploaded_file):
    products_dir = os.path.join(settings.MEDIA_ROOT, 'products')
    os.makedirs(products_dir, exist_ok=True)

    file_path = os.path.join(products_dir, uploaded_file.name)

    with open(file_path, 'wb+') as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    return f'products/{uploaded_file.name}'


def send_order_email(order_id, customer_name, phone, address, comment, cart_items, total_sum):
    order_text = f"""
Новый заказ №{order_id}

Покупатель: {customer_name}
Телефон: {phone}
Адрес доставки: {address}
Комментарий: {comment if comment else 'Без комментария'}

Товары:
"""

    for item in cart_items:
        order_text += f"""
- {item[2]}
  Цена: {item[3]} ₽
  Количество: {item[4]}
  Сумма: {item[5]} ₽
"""

    order_text += f"""

Итого: {total_sum} ₽
"""

    msg = MIMEText(order_text, 'plain', 'utf-8')
    msg['Subject'] = f'Новый заказ №{order_id}'
    msg['From'] = settings.EMAIL_HOST_USER
    msg['To'] = settings.EMAIL_HOST_USER

    with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=10) as server:
        server.starttls()
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        server.send_message(msg)


def home(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT username FROM auth_user ORDER BY id")
        users = cursor.fetchall()

    return render(request, 'shop/home.html', {'users': users})


def catalog(request):
    role = get_user_role(request.user)
    filter_type = request.GET.get('type', 'all')
    search_query = request.GET.get('q', '').strip()

    query = """
        SELECT 
            p.id,
            p.name,
            p.description,
            p.price,
            p.image,
            p.stock,
            c.name AS category_name,
            p.is_bouquet
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE 1=1
    """
    params = []

    if filter_type == 'bouquets':
        query += " AND p.is_bouquet = TRUE"
    elif filter_type == 'single':
        query += " AND p.is_bouquet = FALSE"

    if search_query:
        query += """
            AND (
                p.name ILIKE %s
                OR p.description ILIKE %s
            )
        """
        search_pattern = f"%{search_query}%"
        params.extend([search_pattern, search_pattern])

    query += " ORDER BY p.id"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        products = cursor.fetchall()

    return render(request, 'shop/catalog.html', {
        'products': products,
        'role': role,
        'active_filter': filter_type,
        'search_query': search_query
    })


def add_product(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    role = get_user_role(request.user)
    if role not in ['owner', 'admin']:
        messages.error(request, 'У вас нет прав для добавления товара')
        return redirect('catalog')

    with connection.cursor() as cursor:
        cursor.execute("SELECT id, name FROM categories ORDER BY id")
        categories = cursor.fetchall()

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '').strip()
        stock = request.POST.get('stock', '').strip()
        category_id = request.POST.get('category_id', '').strip()
        is_bouquet = request.POST.get('is_bouquet') == 'on'
        image_file = request.FILES.get('image')

        if not name or not description or not price or not stock or not category_id or not image_file:
            messages.error(request, 'Заполните все поля и выберите изображение')
            return render(request, 'shop/add_product.html', {'categories': categories})

        try:
            image_name = save_uploaded_file(image_file)

            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO products 
                    (name, description, price, image, stock, category_id, is_bouquet)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, [name, description, price, image_name, stock, category_id, is_bouquet])

            messages.success(request, 'Товар успешно добавлен')
            return redirect('catalog')

        except Exception as e:
            print('ADD PRODUCT ERROR:', e)
            messages.error(request, 'Ошибка при добавлении товара')

    return render(request, 'shop/add_product.html', {'categories': categories})


def add_to_cart(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    if request.method != 'POST':
        return redirect('catalog')

    product_id = request.POST.get('product_id')

    try:
        with transaction.atomic():
            cart_id = get_or_create_cart(request.user.id)

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT stock
                    FROM products
                    WHERE id = %s
                """, [product_id])
                product_row = cursor.fetchone()

                if not product_row:
                    messages.error(request, 'Товар не найден')
                    return redirect('catalog')

                stock = product_row[0]

                if stock <= 0:
                    messages.error(request, 'Товара нет в наличии')
                    return redirect('catalog')

                cursor.execute("""
                    SELECT id, quantity
                    FROM cart_items
                    WHERE cart_id = %s AND product_id = %s
                """, [cart_id, product_id])
                existing_item = cursor.fetchone()

                if existing_item:
                    cursor.execute("""
                        UPDATE cart_items
                        SET quantity = quantity + 1
                        WHERE cart_id = %s AND product_id = %s
                    """, [cart_id, product_id])
                else:
                    cursor.execute("""
                        INSERT INTO cart_items (cart_id, product_id, quantity)
                        VALUES (%s, %s, 1)
                    """, [cart_id, product_id])

                cursor.execute("""
                    UPDATE products
                    SET stock = stock - 1
                    WHERE id = %s
                """, [product_id])

        messages.success(request, 'Товар добавлен в корзину')
    except Exception as e:
        print('ADD TO CART ERROR:', e)
        messages.error(request, 'Ошибка при добавлении товара в корзину')

    return redirect('catalog')


def cart_view(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id
            FROM carts
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT 1
        """, [request.user.id])
        cart_row = cursor.fetchone()

        if not cart_row:
            cart_items = []
        else:
            cart_id = cart_row[0]
            cursor.execute("""
                SELECT
                    ci.id,
                    p.name,
                    p.price,
                    ci.quantity,
                    p.image,
                    (p.price * ci.quantity) AS total_price,
                    p.id
                FROM cart_items ci
                JOIN products p ON ci.product_id = p.id
                WHERE ci.cart_id = %s
                ORDER BY ci.id DESC
            """, [cart_id])
            cart_items = cursor.fetchall()

    total_sum = sum(item[5] for item in cart_items) if cart_items else 0

    return render(request, 'shop/cart.html', {
        'cart_items': cart_items,
        'total_sum': total_sum
    })


def remove_from_cart(request, cart_id):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT ci.product_id, ci.quantity
                    FROM cart_items ci
                    JOIN carts c ON ci.cart_id = c.id
                    WHERE ci.id = %s AND c.user_id = %s
                """, [cart_id, request.user.id])
                row = cursor.fetchone()

                if not row:
                    messages.error(request, 'Товар в корзине не найден')
                    return redirect('cart')

                product_id, quantity = row

                cursor.execute("""
                    UPDATE products
                    SET stock = stock + 1
                    WHERE id = %s
                """, [product_id])

                if quantity > 1:
                    cursor.execute("""
                        UPDATE cart_items
                        SET quantity = quantity - 1
                        WHERE id = %s
                    """, [cart_id])
                else:
                    cursor.execute("""
                        DELETE FROM cart_items
                        WHERE id = %s
                    """, [cart_id])

        messages.success(request, 'Количество товара в корзине уменьшено')
    except Exception as e:
        print('REMOVE FROM CART ERROR:', e)
        messages.error(request, 'Ошибка при удалении товара из корзины')

    return redirect('cart')


def checkout(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id
            FROM carts
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT 1
        """, [request.user.id])
        cart_row = cursor.fetchone()

    if not cart_row:
        messages.error(request, 'Корзина пуста')
        return redirect('cart')

    cart_id = cart_row[0]

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                ci.id,
                p.id,
                p.name,
                p.price,
                ci.quantity,
                (p.price * ci.quantity) AS total_price
            FROM cart_items ci
            JOIN products p ON p.id = ci.product_id
            WHERE ci.cart_id = %s
            ORDER BY ci.id
        """, [cart_id])
        cart_items = cursor.fetchall()

    if not cart_items:
        messages.error(request, 'Корзина пуста')
        return redirect('cart')

    total_sum = sum(item[5] for item in cart_items)

    if request.method == 'POST':
        customer_name = request.POST.get('customer_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()
        comment = request.POST.get('comment', '').strip()

        if not customer_name or not phone or not address:
            messages.error(request, 'Заполните имя, телефон и адрес доставки')
            return render(request, 'shop/checkout.html', {
                'cart_items': cart_items,
                'total_sum': total_sum
            })

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO orders
                        (
                            user_id,
                            total_price,
                            status,
                            customer_name,
                            phone,
                            address,
                            comment
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, [
                        request.user.id,
                        total_sum,
                        'Новый заказ',
                        customer_name,
                        phone,
                        address,
                        comment
                    ])

                    order_id = cursor.fetchone()[0]

                    for item in cart_items:
                        product_id = item[1]
                        price = item[3]
                        quantity = item[4]

                        cursor.execute("""
                            INSERT INTO order_items
                            (order_id, product_id, quantity, price)
                            VALUES (%s, %s, %s, %s)
                        """, [order_id, product_id, quantity, price])

                    cursor.execute("""
                        DELETE FROM cart_items
                        WHERE cart_id = %s
                    """, [cart_id])

            send_order_email(
                order_id,
                customer_name,
                phone,
                address,
                comment,
                cart_items,
                total_sum
            )

            messages.success(request, 'Заказ успешно оформлен. Данные отправлены администратору.')
            return redirect('home')

        except Exception as e:
            print('CHECKOUT ERROR:', e)
            messages.error(request, 'Ошибка при оформлении заказа')
            return redirect('checkout')

    return render(request, 'shop/checkout.html', {
        'cart_items': cart_items,
        'total_sum': total_sum
    })


def edit_product(request, product_id):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    role = get_user_role(request.user)
    if role not in ['owner', 'admin']:
        messages.error(request, 'У вас нет прав для редактирования товара')
        return redirect('catalog')

    with connection.cursor() as cursor:
        cursor.execute("SELECT id, name FROM categories ORDER BY id")
        categories = cursor.fetchall()

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '').strip()
        stock = request.POST.get('stock', '').strip()
        category_id = request.POST.get('category_id', '').strip()
        is_bouquet = request.POST.get('is_bouquet') == 'on'
        image_file = request.FILES.get('image')

        if not name or not description or not price or not stock or not category_id:
            messages.error(request, 'Заполните все обязательные поля')
            return redirect(f'/edit-product/{product_id}/')

        try:
            with connection.cursor() as cursor:
                if image_file:
                    image_name = save_uploaded_file(image_file)
                    cursor.execute("""
                        UPDATE products
                        SET name = %s,
                            description = %s,
                            price = %s,
                            image = %s,
                            stock = %s,
                            category_id = %s,
                            is_bouquet = %s
                        WHERE id = %s
                    """, [name, description, price, image_name, stock, category_id, is_bouquet, product_id])
                else:
                    cursor.execute("""
                        UPDATE products
                        SET name = %s,
                            description = %s,
                            price = %s,
                            stock = %s,
                            category_id = %s,
                            is_bouquet = %s
                        WHERE id = %s
                    """, [name, description, price, stock, category_id, is_bouquet, product_id])

            messages.success(request, 'Товар успешно обновлён')
            return redirect('catalog')

        except Exception as e:
            print('EDIT PRODUCT ERROR:', e)
            messages.error(request, 'Ошибка при редактировании товара')
            return redirect(f'/edit-product/{product_id}/')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, description, price, image, stock, category_id, is_bouquet
            FROM products
            WHERE id = %s
        """, [product_id])
        product = cursor.fetchone()

    if not product:
        messages.error(request, 'Товар не найден')
        return redirect('catalog')

    return render(request, 'shop/edit_product.html', {
        'product': product,
        'categories': categories
    })


def delete_product(request, product_id):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    role = get_user_role(request.user)
    if role not in ['owner', 'admin']:
        messages.error(request, 'У вас нет прав для удаления товара')
        return redirect('catalog')

    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM products WHERE id = %s", [product_id])

        messages.success(request, 'Товар успешно удалён')
    except Exception as e:
        print('DELETE PRODUCT ERROR:', e)
        messages.error(request, 'Ошибка при удалении товара')

    return redirect('catalog')


def ai_recognition(request):
    result = None
    products = []
    no_products_message = None

    MIN_CONFIDENCE = 80

    if request.method == 'POST':
        image = request.FILES.get('image')

        if image:
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
            os.makedirs(upload_dir, exist_ok=True)

            upload_path = os.path.join(upload_dir, image.name)

            with open(upload_path, 'wb+') as destination:
                for chunk in image.chunks():
                    destination.write(chunk)

            prediction = predict_flower(upload_path)

            flower_name_en = prediction['flower'].strip().lower()
            flower_name_en = flower_name_en.replace(' ', '_').replace('-', '_')
            confidence = prediction['confidence']

            flower_aliases = {
                'calla': 'calla_lily',
                'calla_lily': 'calla_lily',
                'calla_lilly': 'calla_lily',
                'protea': 'protea',
                'rose': 'rose',
                'tulip': 'tulip',
                'daisy': 'daisy',
                'chrysanthemum': 'chrysanthemum',
            }

            flower_name_en = flower_aliases.get(flower_name_en, flower_name_en)

            print("AI FLOWER:", flower_name_en)
            print("AI CONFIDENCE:", confidence)

            if confidence < MIN_CONFIDENCE:
                result = {
                    'flower_en': flower_name_en,
                    'flower_ru': 'неизвестный цветок',
                    'confidence': confidence,
                    'info': 'Данного цветка нет в нашем магазине.'
                }

                no_products_message = 'Данного цветка нет в нашем магазине.'

                return render(request, 'shop/ai_recognition.html', {
                    'result': result,
                    'products': products,
                    'no_products_message': no_products_message
                })

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, name_ru, short_info
                    FROM flowers
                    WHERE name_en = %s
                    LIMIT 1
                """, [flower_name_en])

                flower_row = cursor.fetchone()

            if flower_row:
                flower_id = flower_row[0]
                flower_name_ru = flower_row[1]
                short_info = flower_row[2]

                result = {
                    'flower_en': flower_name_en,
                    'flower_ru': flower_name_ru,
                    'confidence': confidence,
                    'info': short_info
                }

                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT DISTINCT
                            p.id,
                            p.name,
                            p.description,
                            p.price,
                            p.image,
                            p.stock,
                            p.is_bouquet
                        FROM products p
                        JOIN product_flowers pf ON pf.product_id = p.id
                        WHERE pf.flower_id = %s
                        ORDER BY p.is_bouquet DESC, p.id
                    """, [flower_id])

                    products = cursor.fetchall()

                if not products:
                    no_products_message = 'Данного цветка нет в нашем магазине.'

            else:
                result = {
                    'flower_en': flower_name_en,
                    'flower_ru': 'неизвестный цветок',
                    'confidence': confidence,
                    'info': 'Данного цветка нет в нашем магазине.'
                }

                no_products_message = 'Данного цветка нет в нашем магазине.'

    return render(request, 'shop/ai_recognition.html', {
        'result': result,
        'products': products,
        'no_products_message': no_products_message
    })