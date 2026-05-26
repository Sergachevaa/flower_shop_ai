from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.user_login, name='login'),
    path('two-factor/', views.two_factor_verify, name='two_factor'),
    path('logout/', views.user_logout, name='logout'),
]