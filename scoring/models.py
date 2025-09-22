from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    mobile_number = models.CharField(max_length=20)
    country_code = models.CharField(max_length=10)
    signup_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username
