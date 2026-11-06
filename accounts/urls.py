from django.urls import path
from .views import add_member, business_select, members, profile, remove_member
urlpatterns = [path("", business_select, name="business_select"),
               path("accounts/profile/", profile, name="profile"),
               path("business/<int:business_id>/members/", members, name="members"),
               path("business/<int:business_id>/members/add/", add_member, name="add_member"),
               path("business/<int:business_id>/members/<int:membership_id>/remove/", remove_member, name="remove_member")]
