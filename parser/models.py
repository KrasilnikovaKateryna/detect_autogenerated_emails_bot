from django.db import models

class AutoNews(models.Model):
    sender_name = models.CharField(max_length=255)
    sender_email = models.EmailField()
    content = models.TextField()
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.sent_at} ({self.sender_name})"



class UserNews(models.Model):
    sender_name = models.CharField(max_length=255)
    sender_email = models.EmailField()
    content = models.TextField()
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.sent_at} ({self.sender_name})"

