from django.contrib import messages
from django.db import connection
from django.shortcuts import render, redirect
import os
from django.conf import settings

def get_user_role(user):
    if not user.is_authenticated:
        return None

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM auth_user WHERE id = %s", [user.id])
        row = cursor.fetchone()

    return row[0] if row else None

def home(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT username FROM auth_user")
        users = cursor.fetchall()

    return render(request, 'shop/home.html', {'users': users})


def catalog(request):
    role = None

    if request.user.is_authenticated:
        with connection.cursor() as cursor:
            cursor.execute("SELECT role FROM auth_user WHERE id = %s", [request.user.id])
            row = cursor.fetchone()
            if row:
                role = row[0]

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, description, price, image, stock
            FROM products
            ORDER BY id
        """)
        products = cursor.fetchall()

    return render(request, 'shop/catalog.html', {
        'products': products,
        'role': role
    })

def add_product(request):
    role = get_user_role(request.user)

    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    if role not in ['owner', 'admin']:
        messages.error(request, 'У вас нет прав для добавления товара')
        return redirect('catalog')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '').strip()
        stock = request.POST.get('stock', '').strip()
        image_file = request.FILES.get('image')

        if not name or not description or not price or not stock or not image_file:
            messages.error(request, 'Заполните все поля и выберите изображение')
            return render(request, 'shop/add_product.html')

        try:
            products_dir = os.path.join(settings.MEDIA_ROOT, 'products')
            os.makedirs(products_dir, exist_ok=True)

            file_path = os.path.join(products_dir, image_file.name)

            with open(file_path, 'wb+') as destination:
                for chunk in image_file.chunks():
                    destination.write(chunk)

            image_name = f'products/{image_file.name}'

            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO products (name, description, price, image, stock)
                    VALUES (%s, %s, %s, %s, %s)
                """, [name, description, price, image_name, stock])

            messages.success(request, 'Товар успешно добавлен')
            return redirect('catalog')

        except Exception:
            messages.error(request, 'Ошибка при добавлении товара')

    return render(request, 'shop/add_product.html')

def add_to_cart(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    if request.method == 'POST':
        product_id = request.POST.get('product_id')

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, quantity
                FROM cart
                WHERE user_id = %s AND product_id = %s
            """, [request.user.id, product_id])
            existing_item = cursor.fetchone()

            if existing_item:
                cursor.execute("""
                    UPDATE cart
                    SET quantity = quantity + 1
                    WHERE user_id = %s AND product_id = %s
                """, [request.user.id, product_id])
            else:
                cursor.execute("""
                    INSERT INTO cart (user_id, product_id, quantity)
                    VALUES (%s, %s, 1)
                """, [request.user.id, product_id])

        messages.success(request, 'Товар добавлен в корзину')
        return redirect('catalog')

    return redirect('catalog')


def cart_view(request):
    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                cart.id,
                products.name,
                products.price,
                cart.quantity,
                products.image,
                (products.price * cart.quantity) AS total_price
            FROM cart
            JOIN products ON cart.product_id = products.id
            WHERE cart.user_id = %s
            ORDER BY cart.id DESC
        """, [request.user.id])

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

    with connection.cursor() as cursor:
        cursor.execute("""
            DELETE FROM cart
            WHERE id = %s AND user_id = %s
        """, [cart_id, request.user.id])

    messages.success(request, 'Товар удалён из корзины')
    return redirect('cart')

def edit_product(request, product_id):
    role = get_user_role(request.user)

    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    if role not in ['owner', 'admin']:
        messages.error(request, 'У вас нет прав для редактирования товара')
        return redirect('catalog')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '').strip()
        image = request.POST.get('image', '').strip()
        stock = request.POST.get('stock', '').strip()

        if not name or not description or not price or not image or not stock:
            messages.error(request, 'Заполните все поля')
            return redirect(f'/edit-product/{product_id}/')

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE products
                SET name = %s,
                    description = %s,
                    price = %s,
                    image = %s,
                    stock = %s
                WHERE id = %s
            """, [name, description, price, image, stock, product_id])

        messages.success(request, 'Товар успешно обновлён')
        return redirect('catalog')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, description, price, image, stock
            FROM products
            WHERE id = %s
        """, [product_id])
        product = cursor.fetchone()

    if not product:
        messages.error(request, 'Товар не найден')
        return redirect('catalog')

    return render(request, 'shop/edit_product.html', {'product': product})


def delete_product(request, product_id):
    role = get_user_role(request.user)

    if not request.user.is_authenticated:
        messages.error(request, 'Сначала войдите в систему')
        return redirect('login')

    if role not in ['owner', 'admin']:
        messages.error(request, 'У вас нет прав для удаления товара')
        return redirect('catalog')

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM products WHERE id = %s", [product_id])

    messages.success(request, 'Товар успешно удалён')
    return redirect('catalog')