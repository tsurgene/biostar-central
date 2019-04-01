
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction

from biostar.utils.shortcuts import reverse
from . import forms, auth
from .models import Post, Vote
from biostar.utils.decorators import ajax_error, ajax_error_wrapper, ajax_success, object_exists
from .const import *


User = get_user_model()


def get_topics(user):
    """Return dict of all topics viewable by user."""

    all_topics = {
        JOBS: Post.objects.top_level(user).filter(type=Post.JOB),
        TOOLS: Post.objects.top_level(user).filter(type=Post.TOOL),
        TUTORIALS: Post.objects.top_level(user).filter(type=Post.TUTORIAL),
        FORUM: Post.objects.top_level(user).filter(type=Post.FORUM),
        PLANET: Post.objects.top_level(user).filter(type=Post.BLOG),
        MYPOSTS: Post.objects.my_posts(target=user, user=user),
        OPEN: Post.objects.top_level(user=user),
        LATEST: Post.objects.top_level(user=user),
        BOOKMARKS: Post.objects.my_bookmarks(user=user) if user.is_authenticated else Post.objects.none(),
        FOLLOWING: Post.objects.following(user=user) if user.is_authenticated else Post.objects.none(),
        VOTES: Post.objects.my_post_votes(user=user) if user.is_authenticated else Post.objects.none(),
    }

    return all_topics


def post_list(request):

    # Get current topic
    topic = request.GET.get("active", "latest")
    tag = request.GET.get("tag", "")
    user = request.user

    if user.is_anonymous and topic in PRIVATE_TOPICS:
        messages.error(request, f"You must be logged in to view that topic.")
        return redirect(reverse("post_list"))

    all_topics = get_topics(user=user)

    topic = topic.lower()
    posts = all_topics.get(topic, Post.objects.top_level(user))
    if topic == OPEN:
        posts = posts.filter(type=Post.QUESTION, reply_count=0)

    if tag:
        posts = posts.filter(tag_val__iregex=tag)

    # Exclude deleted posts
    if user.is_authenticated and not user.profile.is_moderator:
        posts = posts.exclude(status=Post.DELETED)

    # Return latest posts by default.
    if posts is None:
        posts = Post.objects.top_level(user)

    # Get the page info
    posts = posts.order_by("rank", "-lastedit_date")
    page = request.GET.get('page')
    paginator = Paginator(posts, settings.POSTS_PER_PAGE)
    posts = paginator.get_page(page)

    context = dict(posts=posts, active=topic, tag=tag)

    context.update({topic: "active"})
    return render(request, template_name="post_list.html", context=context)


def community_list(request):

    objs = User.objects.select_related("profile").order_by("-last_login")
    paginator = Paginator(objs, settings.USERS_PER_PAGE)
    page = request.GET.get("page", 1)
    objs = paginator.get_page(page)
    context = dict(community="active", objs=objs)

    return render(request, "community_list.html", context=context)


#def tags_list(request):

#    context = dict(extra_tab="active", extra_tab_name="All Tags")
#    return render(request, "tags_list.html", context=context)


@ajax_error_wrapper(method="POST")
def ajax_vote(request):

    user = request.user
    type_map = dict(upvote=Vote.UP, bookmark=Vote.BOOKMARK, accept=Vote.ACCEPT)

    vote_type = request.POST['vote_type']
    vote_type = type_map[vote_type]
    post_uid = request.POST['post_uid']

    # Check the post that is voted on.
    post = Post.objects.get_all(uid=post_uid).first()

    if post.author == user and vote_type == Vote.UP:
        return ajax_error("You can not upvote your own post.")

    if post.author == user and vote_type == Vote.ACCEPT:
        return ajax_error("You can not accept your own post.")

    if post.root.author != user and vote_type == Vote.ACCEPT:
        return ajax_error("Only the person asking the question may accept this answer.")

    msg = auth.preform_vote(post=post, user=user, vote_type=vote_type)

    return ajax_success(msg)


@object_exists(klass=Post)
def post_view(request, uid):
    "Return a detailed view for specific post"

    # Form used for answers
    form = forms.PostShortForm()

    # Get the parents info
    obj = Post.objects.get_all(uid=uid).first()
    # Return root view if not at top level.
    obj = obj if obj.is_toplevel else obj.root

    auth.update_post_views(post=obj, request=request)

    if request.method == "POST":
        form = forms.PostShortForm(data=request.POST)
        if form.is_valid():
            post = form.save(author=request.user)
            location = reverse("post_view", request=request, kwargs=dict(uid=obj.root.uid)) + "#" + post.uid
            return redirect(location)

    # Populate the object to build a tree that contains all posts in the thread.
    # Answers are added here as well.
    comment_tree, answers, thread = auth.build_obj_tree(request=request, obj=obj)

    context = dict(post=obj, tree=comment_tree, form=form, answers=answers)

    return render(request, "post_view.html", context=context)


@login_required
def comment(request):

    location = reverse("post_list")
    if request.method == "POST":
        form = forms.PostShortForm(data=request.POST)
        if form.is_valid():
            post = form.save(author=request.user, post_type=Post.COMMENT)
            messages.success(request, "Added comment")

            location = reverse("post_view", kwargs=dict(uid=post.uid)) + "#" + post.uid
        else:
            messages.error(request, f"Error adding comment:{form.errors}")
            parent = Post.objects.get_all(uid=request.POST.get("parent_uid")).first()
            location = location if parent is None else reverse("post_view", kwargs=dict(uid=parent.root.uid))

    return redirect(location)


@object_exists(klass=Post)
@login_required
def subs_action(request, uid, next=None):

    # Post actions are being taken on
    post = Post.objects.get_all(uid=uid).first()
    user = request.user
    next_url = request.GET.get(REDIRECT_FIELD_NAME,
                               request.POST.get(REDIRECT_FIELD_NAME))
    next_url = next or next_url or "/"

    if request.method == "POST" and user.is_authenticated:
        form = forms.SubsForm(data=request.POST, post=post, user=user)

        if form.is_valid():
            sub = form.save()
            msg = f"Updated Subscription to : {sub.get_type_display()}"
            messages.success(request, msg)

    return redirect(next_url)


@login_required
def post_create(request, project=None, template="post_create.html", url="post_view",
                extra_context={}, filter_func=lambda x: x):
    "Make a new post"

    # Filter function ( filter_func ) is used to filter choices from the form
    # between sites.
    form = forms.PostLongForm(project=project, filter_func=filter_func)

    if request.method == "POST":
        form = forms.PostLongForm(data=request.POST, project=project, filter_func=filter_func)
        if form.is_valid():
            # Create a new post by user
            post = form.save(author=request.user)
            return redirect(reverse(url, request=request, kwargs=dict(uid=post.uid)))

    context = dict(form=form, extra_tab="active", extra_tab_name="New Post", action_url=reverse("post_create"))
    context.update(extra_context)

    return render(request, template, context=context)


@object_exists(klass=Post)
@login_required
def post_moderate(request, uid):

    user = request.user
    post = Post.objects.get_all(uid=uid).first()
    form = forms.PostModForm(post=post, user=user, request=request)

    if request.method == "POST":

        form = forms.PostModForm(post=post, data=request.POST, user=user, request=request)
        if form.is_valid():
            url = form.save()
            return redirect(url)
        else:
            msg = ','.join([y for x in form.errors.values() for y in x])
            messages.error(request, msg)
            return redirect(post.root.get_absolute_url())

    context = dict(form=form, post=post)
    return render(request, "post_moderate.html", context)


@object_exists(klass=Post)
@login_required
def edit_post(request, uid):
    "Edit an existing post"

    post = Post.objects.get_all(uid=uid).first()
    if post.is_toplevel:
        template, edit_form = "post_create.html", forms.PostLongForm
    else:
        template, edit_form = "shortpost_edit.html", forms.PostShortForm

    user = request.user
    form = edit_form(post=post, user=user)
    if request.method == "POST":
        form = edit_form(post=post, data=request.POST, user=user)
        if form.is_valid():
            form.save(edit=True)
            messages.success(request, f"Edited :{post.title}")
            return redirect(reverse("post_view", kwargs=dict(uid=uid)))

    context = dict(form=form, post=post, action_url=reverse("post_edit", kwargs=dict(uid=uid)),
                   extra_tab="active", extra_tab_name="Edit Post")

    return render(request, template, context)





