import random
import smtplib
import time

from email.mime.text import MIMEText

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.shortcuts import render, redirect


# =========================
# ОТПРАВКА EMAIL
# =========================

def send_2fa_email(to_email, code):
    msg = MIMEText(
        f'Ваш код подтверждения для входа: {code}\n\nКод действует 5 минут.',
        'plain',
        'utf-8'
    )

    msg['Subject'] = 'Код подтверждения входа'
    msg['From'] = settings.EMAIL_HOST_USER
    msg['To'] = to_email

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(msg)

        return True

    except Exception as e:
        print("EMAIL ERROR:", e)
        return False

# =========================
# РЕГИСТРАЦИЯ
# =========================

def register(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not email or not password:
            messages.error(request, 'Заполните все поля')
            return render(request, 'users/register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Пользователь уже существует')
            return render(request, 'users/register.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email уже используется')
            return render(request, 'users/register.html')

        User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        messages.success(request, 'Регистрация успешна')
        return redirect('login')

    return render(request, 'users/register.html')


# =========================
# ВХОД
# =========================

def user_login(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            messages.error(request, 'Введите логин и пароль')
            return render(request, 'users/login.html')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:

            if not user.email:
                messages.error(request, 'У пользователя не указан email')
                return redirect('login')

            code = str(random.randint(100000, 999999))

            request.session['2fa_user_id'] = user.id
            request.session['2fa_code'] = code
            request.session['2fa_expire'] = time.time() + 300

            email_sent = send_2fa_email(user.email, code)

            if not email_sent:
                messages.error(request, 'Не удалось отправить код на почту. Проверьте SMTP-настройки.')
                print("КОД ДЛЯ ВХОДА:", code)
                return redirect('login')

            messages.success(
                request,
                'Код подтверждения отправлен на email'
            )

            return redirect('two_factor')

        else:
            messages.error(request, 'Неверный логин или пароль')

    return render(request, 'users/login.html')


# =========================
# ПРОВЕРКА КОДА
# =========================

def two_factor_verify(request):

    user_id = request.session.get('2fa_user_id')
    saved_code = request.session.get('2fa_code')
    expire_time = request.session.get('2fa_expire')

    if not user_id or not saved_code:
        messages.error(request, 'Сначала выполните вход')
        return redirect('login')

    if time.time() > expire_time:
        request.session.flush()

        messages.error(request, 'Код подтверждения истёк')
        return redirect('login')

    if request.method == 'POST':

        entered_code = request.POST.get('code', '').strip()

        if entered_code == saved_code:

            user = User.objects.get(id=user_id)

            login(request, user)

            request.session.pop('2fa_user_id', None)
            request.session.pop('2fa_code', None)
            request.session.pop('2fa_expire', None)

            messages.success(request, 'Вход выполнен успешно')

            return redirect('home')

        else:
            messages.error(request, 'Неверный код')

    return render(request, 'users/two_factor.html')


# =========================
# ВЫХОД
# =========================

def user_logout(request):
    logout(request)

    messages.success(request, 'Вы вышли из системы')

    return redirect('home')