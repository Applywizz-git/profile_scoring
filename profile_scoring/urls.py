from django.urls import path
from scoring import views
from django.conf.urls.static import static
from django.conf import settings



urlpatterns = [
    # Basic Views
    path('', views.landing, name='landing'),
    path('signin/', views.signin, name='signin'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup, name='signup'),
    path('about_us/', views.about_us, name='about_us'),
    path('why/', views.why, name='why'),
    path('who/', views.who, name='who'),

    # OTP Views
   path("send-signup-otp", views.send_signup_otp, name="send_signup_otp"),
    path("verify-signup-otp", views.verify_signup_otp, name="verify_signup_otp"),

    # LOGIN (email -> email OTP)
    path("send-email-otp", views.send_login_otp, name="send_email_otp"),
    path("verify-email-otp", views.verify_login_otp, name="verify_email_otp"),

    # Resume Analyzer Views
    path('upload_resume/', views.upload_resume, name='upload_resume'),
    path('analyze_resume/', views.analyze_resume, name='analyze_resume'),
    path('analyze_resume/', views.analyze_resume, name='analyze_resume'),
    path('analyze_resume_v2/', views.analyze_resume_v2, name='analyze_resume_v2'),

    # Profile Building & Payment Views
    path('download_resume_report/', views.download_resume_pdf, name='download_resume_report'),

    path("report/technical/", views.show_report_technical, name="show_report_technical"),
    path("report/non-technical/", views.show_report_nontechnical, name="show_report_nontechnical"),


]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Local static (only when DEBUG=True)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)