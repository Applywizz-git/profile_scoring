from django.contrib import admin
from django.urls import path
from scoring import views  # Import views from scoring app

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.landing_page, name='landing'),
    path('login/', views.login_page, name='login'),
    path('why/', views.why, name='why'),
    path('who/', views.who, name='who'),
    path("send-signup-otp", views.send_signup_otp, name="send_signup_otp"),
    path("verify-signup-otp", views.verify_signup_otp, name="verify_signup_otp"),

    # LOGIN (email -> email OTP)
    path("send-email-otp", views.send_login_otp, name="send_email_otp"),
    path("verify-email-otp", views.verify_login_otp, name="verify_email_otp"),
    # path('send-email-otp/', views.send_email_otp, name='send_email_otp'),  # New route to send OTP
    path('upload_resume/', views.upload_resume, name='upload_resume'),
    path('analyze_resume/', views.analyze_resume, name='analyze_resume'), 
    # path('profile_report/', views.profile_report, name='profile_report'),
]
