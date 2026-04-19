from django.urls import path
from .views import (
    home,
    catalog,
    add_product,
    add_to_cart,
    cart_view,
    remove_from_cart,
    edit_product,
    delete_product,
)

urlpatterns = [
    path('', home, name='home'),
    path('catalog/', catalog, name='catalog'),
    path('add-product/', add_product, name='add_product'),
    path('add-to-cart/', add_to_cart, name='add_to_cart'),
    path('cart/', cart_view, name='cart'),
    path('remove-from-cart/<int:cart_id>/', remove_from_cart, name='remove_from_cart'),
    path('edit-product/<int:product_id>/', edit_product, name='edit_product'),
    path('delete-product/<int:product_id>/', delete_product, name='delete_product'),
]