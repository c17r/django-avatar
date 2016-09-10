from django.utils import six
from django.utils.translation import ugettext as _

from django.contrib import messages

from django.contrib.auth import mixins
from django.views import generic
from django.utils.encoding import force_text

from avatar.conf import settings
from avatar.forms import PrimaryAvatarForm, DeleteAvatarForm, UploadAvatarForm
from avatar.models import Avatar
from avatar.signals import avatar_updated
from avatar.utils import (get_primary_avatar, get_default_avatar_url,
                          invalidate_cache)


class Base(mixins.LoginRequiredMixin, generic.FormView):
    extra_context = None
    next_override = None

    def get_avatars(self):
        if hasattr(self, '_get_avatars'):
            return self._get_avatars

        avatars = self.request.user.avatar_set.all()
        avatar = None

        primary_avatar = avatars.order_by('-primary')[:1]
        if primary_avatar:
            avatar = primary_avatar[0]

        if settings.AVATAR_MAX_AVATARS_PER_USER == 1:
            avatars = primary_avatar
        else:
            avatars = avatars[:settings.AVATAR_MAX_AVATARS_PER_USER]

        self._get_avatars = (avatar, avatars)
        return self._get_avatars

    def get_context_data(self, **kwargs):
        avatar, avatars = self.get_avatars()
        context = super(Base, self).get_context_data(**kwargs)
        context.update({
            'avatar': avatar,
            'avatars': avatars
        })
        if self.extra_context:
            context.update(self.extra_context)

        return context

    def get_form_kwargs(self):
        kwargs = super(Base, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        if self.next_override:
            return self.next_override

        if self.success_url:
            return force_text(self.success_url)

        url = self.request.POST.get('next')
        if not url:
            url = self.request.GET.get('next')
        if not url:
            url = self.request.META.get('HTTP_REFERER')
        if not url:
            url = self.request.path
        if url:
            return url

    def add_avatar(self, form):
        avatar = Avatar(user=self.request.user, primary=True)
        image_file = self.request.FILES['avatar']
        avatar.avatar.save(image_file.name, image_file)
        avatar.save()
        messages.success(self.request, _("Successfully uploaded a new avatar."))
        avatar_updated.send(sender=Avatar, user=self.request.user, avatar=avatar)


class Add(Base):
    template_name = 'avatar/add.html'
    form_class = UploadAvatarForm

    def form_valid(self, form):
        self.add_avatar(form)
        return super(Add, self).form_valid(form)


class Change(Base):
    template_name = 'avatar/change.html'
    form_class = PrimaryAvatarForm
    upload_form_class = UploadAvatarForm

    def get_context_data(self, **kwargs):
        context = super(Change, self).get_context_data(**kwargs)
        if 'upload_form' not in context:
            context['upload_form'] = self.get_upload_form()
        return context

    def get_initial(self):
        avatar, _ = self.get_avatars()
        if avatar:
            return {'choice': avatar.id}
        return super(Change, self).get_initial()

    def get_form_kwargs(self):
        _, avatars = self.get_avatars()
        kwargs = super(Change, self).get_form_kwargs()
        kwargs['avatars'] = avatars
        return kwargs

    def get_upload_form(self):
        kwargs = self.get_form_kwargs()
        if 'avatars' in kwargs:
            del kwargs['avatars']
        return self.upload_form_class(**kwargs)

    def is_valid(self, form, upload_form):
        if 'choice' in self.request.POST:
            if form.is_valid():
                return True
        if 'avatar' in self.request.FILES:
            if upload_form.is_valid():
                return True
        return False

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        upload_form = self.get_upload_form()
        if self.is_valid(form, upload_form):
            return self.form_valid(form, upload_form)
        else:
            return self.form_invalid(form=form, upload_form=upload_form)

    def form_invalid(self, **kwargs):
        return self.render_to_response(self.get_context_data(**kwargs))

    def form_valid(self, form, upload_form):
        if 'choice' in self.request.POST and form.is_valid():
            a_id = form.cleaned_data['choice']
            avatar = Avatar.objects.get(id=a_id)
            avatar.primary = True
            avatar.save()
            invalidate_cache(self.request.user)
            messages.success(self.request, _("Successfully updated your avatar."))
            avatar_updated.send(sender=Avatar, user=self.request.user,
                                avatar=avatar)

        if 'avatar' in self.request.FILES and upload_form.is_valid():
            self.add_avatar(upload_form)

        return super(Change, self).form_valid(form)


class Delete(Base):
    template_name = 'avatar/confirm_delete.html'
    form_class = DeleteAvatarForm

    def get_form_kwargs(self):
        _, avatars = self.get_avatars()
        kwargs = super(Delete, self).get_form_kwargs()
        kwargs['avatars'] = avatars
        return kwargs

    def form_valid(self, form):
        avatar, avatars = self.get_avatars()
        ids = form.cleaned_data['choices']
        if six.text_type(avatar.id) in ids and avatars.count() > len(ids):
            for a in avatars:
                if six.text_type(a.id) not in ids:
                    a.primary = True
                    a.save()
                    avatar_updated.send(sender=Avatar, user=self.request.user,
                                        avatar=avatar)
                    break
        Avatar.objects.filter(id__in=ids).delete()
        messages.success(self.request,
                        _("Successfully deleted the requested avatars."))
        return super(Delete, self).form_valid(form)


class RenderPrimary(generic.RedirectView):
    def get_redirect_url(self, *args, **kwargs):
        size = int(self.kwargs.get('size', settings.AVATAR_DEFAULT_SIZE))
        user = self.kwargs.get('user')

        avatar = get_primary_avatar(user, size=size)
        if avatar:
            # FIXME: later, add an option to render the resized avatar dynamically
            # instead of redirecting to an already created static file. This could
            # be useful in certain situations, particulary if there is a CDN and
            # we want to minimize the storage usage on our static server, letting
            # the CDN store those files instead
            url = avatar.avatar_url(size)
        else:
            url = get_default_avatar_url()

        return url
