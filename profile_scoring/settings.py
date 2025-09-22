from pathlib import Path
import environ
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# =====================
# Load .env file (optional)
# =====================
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# =====================
# Security settings
# =====================
SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)  # Use the DEBUG value from the .env file
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost'])
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=['http://localhost:8000'])

# =====================
# Application definition
# =====================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'scoring',  # Your app
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'profile_scoring.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'profile_scoring.wsgi.application'

# =====================
# Database settings
# =====================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME', default='mydb'),
        'USER': env('DB_USER', default='myuser'),
        'PASSWORD': env('DB_PASSWORD', default='mypassword'),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default=5432),
    }
}

# Use DATABASE_URL for deployment
import dj_database_url
DATABASES['default'] = dj_database_url.config(default=env('DATABASE_URL'), conn_max_age=600, ssl_require=True)

# =====================
# Password validation
# =====================
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# =====================
# Email settings for Outlook
# =====================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.office365.com'  # SMTP server for Outlook
EMAIL_PORT = 587  # Standard port for TLS
EMAIL_USE_TLS = True  # Use TLS encryption
EMAIL_HOST_USER = env('OUTLOOK_SENDER_EMAIL')  # Your Outlook email (e.g., 'you@domain.com')
EMAIL_HOST_PASSWORD = env('OUTLOOK_CLIENT_SECRET')  # Your application password or client secret (if OAuth2 isn't set up)
DEFAULT_FROM_EMAIL = env('OUTLOOK_SENDER_EMAIL')  # Same email as your sender email
EMAIL_TIMEOUT = env('EMAIL_TIMEOUT', cast=int, default=30)  # Timeout for sending emails

# =====================
# Static files settings
# =====================
STATIC_URL = '/static/'

# For Vercel, use the STATIC_URL with Vercel's file system, which uses the '/static' folder by default
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files settings
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# =====================
# Default primary key field type
# =====================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =====================
# Django Vercel settings
# =====================
# These settings are crucial for deploying on Vercel
import dj_database_url
DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)

# Secure the app for production
SECURE_SSL_REDIRECT = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
