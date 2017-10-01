from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate
import logging, uuid
import random
from .settings import BASE_DIR
import os
import json

# Random block of latin text (lorem ipsum) to populate text feild
TEXT = "#TEST\nSed ut perspiciatis unde omnis iste natus error\n\
sit voluptatem accusantium doloremque\nlaudantium, totam rem aperiam, eaque ipsa quae ab illo"


def join(*args):
    return os.path.abspath(os.path.join(*args))


logger = logging.getLogger('engine')
JSON_SPECFILE =join(BASE_DIR, '..', 'pipeline',
                'templates','metabarcode_qc', 'metabarcode_spec.json' )


def get_uuid(limit=None):
    return str(uuid.uuid4())[:limit]


def init_proj(sender, **kwargs):
    """
    Populate initial projects with N number data
    Creates one analysis model to allow for jobs to be run
    """
    from engine.models import Project, Data, Analysis
    from engine.models import User

    N = 2
    Y = 2
    owner = User.objects.all().first()
    projects = [f"Project {x}" for x in range(1, 10)][:Y]
    data= [f"Data {x}" for x in range(1, 10)]

    # Make a project
    for title in projects:

        test_set = random.sample(data, N)
        project, flag = Project.objects.get_or_create(title=title, owner=owner, text=TEXT)
        project.save()

        # add some data to the project
        for data_title in test_set:

            datainput, flag = Data.objects.get_or_create(title=data_title,
                                                         owner=owner,
                                                         text=TEXT, project=project)
            datainput.save()


        logger.info(f'creating or getting: {project.title} with {len(test_set)} data.')

    analysis, flag = Analysis.objects.get_or_create(title="Analysis 1",
                                                    owner=owner,
                                                    text=TEXT)
    analysis.save()

    logger.info(f' with: {len(test_set)} data, analysis, and pipelines.')


def init_users(sender, **kwargs):
    """
    Creates admin users if these are not present.
    """
    from engine.models import User
    logger.info("Setting up users")

    for name, email in settings.ADMINS:
        
        if not User.objects.filter(email=email):
            user = User(first_name="foo", email=email, username=get_uuid(16),
                        is_superuser=True, is_staff=True)
            user.set_password(settings.SECRET_KEY)
            user.save()
            logger.info(f"creating admin: user.username = {user.username}, user.email={user.email}")

    # Create a regular test user.
    test_user = User.objects.get_or_create(email="foo@bar.com", password="foobar221")


def init_site(sender, **kwargs):
    """
    Updates site domain and name.
    """
    from django.contrib.sites.models import Site

    # Print information on the database.
    db = settings.DATABASES['default']
    logger.info("db.engine={}, db.name={}".format(db['ENGINE'], db['NAME']))
    logger.info("email.backend={}".format(settings.EMAIL_BACKEND))
    logger.info("default.email={}".format(settings.DEFAULT_FROM_EMAIL))

    # Create the default site if necessary.
    Site.objects.get_or_create(id=settings.SITE_ID)

    # Update the default site domain and name.
    Site.objects.filter(id=settings.SITE_ID).update(domain=settings.SITE_DOMAIN, name=settings.SITE_NAME)

    # Get the current site
    site = Site.objects.get(id=settings.SITE_ID)
    logger.info("site.name={}, site.domain={}".format(site.name, site.domain))


class EngineConfig(AppConfig):
    name = 'engine'

    def ready(self):
        # Triggered upon app initialization.
        post_migrate.connect(init_site, sender=self)
        post_migrate.connect(init_users, sender=self)
        post_migrate.connect(init_proj, sender=self)
        logger.debug("EngineConfig done")



