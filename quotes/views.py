#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import itertools
import re

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.syndication.views import Feed
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.template import Context, loader
from registration import signals
from registration.forms import RegistrationForm
from registration.backends.default.views import RegistrationView
from voting.models import Vote

from .models import Quote

MAX_PAGE = 30


class SearchForm(forms.Form):
    q = forms.CharField()

    def clean_q(self):
        q = self.cleaned_data['q']
        if len(q.split()) > 30:
            raise forms.ValidationError("Trop de mots.")
        if len(q) > 300:
            raise forms.ValidationError("Trop de lettres.")
        return q


class AddQuoteForm(forms.Form):
    author = forms.CharField(label="Auteur")
    context = forms.CharField(label="Contexte", required=False)
    content = forms.CharField(widget=forms.Textarea(attrs={
      'style': 'width: 500px; heigth: 200px;'}), label="")


class UserRegistrationForm(RegistrationForm):
    username = forms.CharField(max_length=64, label='Login EPITA')
    email = None

    class Meta(RegistrationForm.Meta):
        model = User
        fields = [User.USERNAME_FIELD]

    def clean_username(self):
        if User.objects.filter(username=self.data['username']).exists():
            raise forms.ValidationError('Ce login est déjà enregistré.')
        return self.data['username']

    def save(self, *args, **kwargs):
        self.instance.email = self.cleaned_data['username'] + '@epita.fr'
        return super().save(*args, **kwargs)


class UserRegistrationView(RegistrationView):
    form_class = UserRegistrationForm


def template_processor(request):
    return {
        'quotes_search_form': SearchForm(),
    }


def get_quotes(user=None):
    quotes = Quote.objects.filter(accepted=True)
    if not (user and user.is_staff):
        quotes = quotes.filter(visible=True)
    return quotes


def get_quotes_by_vote(user, **kwargs):
    quotes = [x[0] for x in Vote.objects.get_top(Quote, **kwargs)]
    if not user.is_staff:
        quotes = list(filter(lambda x: x.visible, quotes))
    return quotes


def last_quotes(request, p=1):
    if 'p' in request.GET:
        return HttpResponseRedirect('/last/{0}'.format(request.GET['p']))
    quotes = get_quotes(request.user).order_by('-date')
    paginate = Paginator(quotes, MAX_PAGE)
    try:
        page = paginate.page(p)
    except:
        raise Http404()
    return render(request, 'last.html', dict(
        {'name_page': 'Dernières citations', 'page': page}))


def top_quotes(request):
    quotes = get_quotes_by_vote(request.user, limit=50)
    return render(request, 'simple.html', dict(
        {'name_page': 'Meilleures citations', 'quotes': quotes}))


def flop_quotes(request):
    quotes = get_quotes_by_vote(request.user, limit=50, reversed=True)
    return render(request, 'simple.html', dict(
        {'name_page': 'Pires citations', 'quotes': quotes}))


def favourites(request, username):
    try:
        userprofile = User.objects.get(username=username).profile
    except:
        raise Http404()
    quotes = userprofile.quotes.all()
    return render(request, 'simple.html', dict(
        {'name_page': 'Favoris de {0}'.format(username), 'quotes': quotes}))


def home(request):
    last = get_quotes(request.user).order_by('-date')[:5]
    top = get_quotes_by_vote(request.user, limit=5)
    return render(request, 'home.html', {'top': top, 'last': last})


def random_quotes(request):
    quotes = get_quotes(request.user).order_by('?')[:MAX_PAGE]
    return render(request, 'simple.html', {'name_page':
        'Citations aléatoires', 'quotes': quotes})


def show_quote(request, quote_id):
    try:
        quote = get_quotes(request.user).get(id=quote_id)
    except ObjectDoesNotExist:
        raise Http404()
    return render(request, 'quote.html', {'name_page':
        'Citation #{0}'.format(quote_id), 'quotes': [quote]})


def search_quotes(request):
    def quotes_split(s):
        l = map((lambda x: x.strip()), s.split('"'))
        l = [[e] if i % 2 else e.split() for i, e in enumerate(l)]
        return filter(bool, itertools.chain(*l))

    f = SearchForm(request.GET)
    if not f.is_valid():
        raise Http404()
    q = f.cleaned_data['q']
    terms = map(lambda s: r'(^|[^\w]){0}([^\w]|$)'.format(re.escape(s)),
            quotes_split(q))
    if not terms:
        raise Http404()
    f = Q()
    for w in terms:
        f &= (Q(content__iregex=w)
                | Q(context__iregex=w)
                | Q(author__iregex=w))
    quotes = get_quotes(request.user).order_by('-date')
    quotes = quotes.filter(f)
    if not quotes:
        raise Http404()
    return render(request, 'simple.html', {'name_page':
        'Recherche : {0}'.format(request.GET['q']), 'quotes': quotes})


@login_required
def add_quote(request):
    print(type(request.user))
    if request.method == 'POST':
        form = AddQuoteForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            quote = Quote(author=cd['author'], context=cd['context'],
                    content=cd['content'], user=request.user)
            quote.save()
            return HttpResponseRedirect('/add_confirm')
    else:
        form = AddQuoteForm()
    return render(request, 'add.html', {'name_page':
        'Ajouter une citation', 'add_form': form})


@login_required
def add_confirm(request):
    return render(request, 'add_confirm.html', {'name_page':
            'Ajouter une citation'})


@login_required
def favourite(request, quote_id):
    try:
        quote = Quote.objects.get(id=int(quote_id))
    except:
        raise Http404()
    profile = request.user.profile
    if quote in profile.quotes.all():
        profile.quotes.remove(quote)
    else:
        profile.quotes.add(quote)
    profile.save()
    return HttpResponse('')


class LatestFeed(Feed):
    title = 'Epiquote'
    link = '/last'
    description = 'Les dernières citations sur Epiquote'

    def items(self):
        return get_quotes(None).order_by('-date')[:MAX_PAGE]

    def item_title(self, item):
        return '#{0}'.format(item.id)

    def item_description(self, item):
        t = loader.get_template('rss_description.html')
        return t.render(Context({'context': item.context,
            'content': item.content, 'author': item.author}))
