from django.contrib import messages
from django.db import connection, transaction
from django.shortcuts import render, redirect
from django.conf import settings
import os


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
                    INSERT INTO products (name, description, price, image, stock, category_id, is_bouquet)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, [name, description, price, image_name, stock, category_id, is_bouquet])

            messages.success(request, 'Товар успешно добавлен')
            return redirect('catalog')

        except Exception:
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
    except Exception:
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
    except Exception:
        messages.error(request, 'Ошибка при удалении товара из корзины')

    return redirect('cart')


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

        except Exception:
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
    except Exception:
        messages.error(request, 'Ошибка при удалении товара')

    return redirect('catalog')