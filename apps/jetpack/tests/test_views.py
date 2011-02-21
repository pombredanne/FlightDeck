import os
import commonware
import json
import StringIO
import simplejson

from datetime import datetime

from test_utils import TestCase
from nose.tools import eq_
from nose import SkipTest
from mock import patch

#from pyquery import PyQuery as pq

from django.conf import settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from jetpack.models import PackageRevision, Attachment
from jetpack.errors import FilenameExistException
from jetpack.views import latest_by_uid
from base.templatetags.base_helpers import hashtag

log = commonware.log.getLogger('f.test')

def next(revision):
    number = revision.revision_number
    return (PackageRevision.objects.filter(revision_number__gt=number,
                                           package=revision.package)
                                   .order_by('-revision_number')[:1])[0]


class TestViews(TestCase):
    fixtures = ('mozilla_user', 'core_sdk', 'users', 'packages')

    def setUp(self):
        self.hashtag = hashtag()
        self.check_download_url = reverse('jp_check_download_xpi',
                args=[self.hashtag])

    @patch('os.path.isfile')
    def test_package_check_download(self, isfile):
        """
        If we are waiting for the XPI, we'll need to test the redirecty stuff.
        """
        isfile.return_value = False
        r = self.client.get(self.check_download_url)
        eq_(r.status_code, 200)
        eq_(r.content, '{"ready": false}')
        isfile.return_value = True
        r = self.client.get(self.check_download_url)
        eq_(r.status_code, 200)
        eq_(r.content, '{"ready": true}')

    def test_package_browser_no_use(self):
        """If user does not exist raise 404
        """
        r = self.client.get(
                reverse('jp_browser_user_addons', args=['not_a_user']))
        eq_(r.status_code, 404)


class TestAttachments(TestCase):
    fixtures = ['mozilla_user', 'users', 'core_sdk', 'packages']

    def setUp(self):
        if not os.path.exists(settings.UPLOAD_DIR):
            os.makedirs(settings.UPLOAD_DIR)

        self.author = User.objects.get(username='john')
        self.author.set_password('password')
        self.author.save()

        self.package = self.author.packages_originated.addons()[0:1].get()
        self.revision = self.package.revisions.all()[0]
        self.revision_number = 0

        self.add_url = self.get_add_url(self.revision.revision_number)
        self.upload_url = self.get_upload_url(self.revision.revision_number)
        self.change_url = self.get_change_url(self.revision.revision_number)
        self.client.login(username=self.author.username, password='password')

    def test_attachment_error(self):
        res = self.client.post(self.add_url, {})
        eq_(res.status_code, 500)

    def add_one(self, data = 'foo', filename='some.txt'):
        self.upload(self.get_upload_url(self.revision.revision_number), data, filename)
        self.revision = next(self.revision)
        return self.revision

    def get_upload_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_upload_attachment', args=args)

    def get_add_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_add_attachment', args=args)

    def get_change_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_save', args=args)

    def get_delete_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_remove_attachment', args=args)

    def get_revision(self):
        return PackageRevision.objects.get(pk=self.revision.pk)

    def upload(self, url, data, filename):
        # A post that matches the JS and uses raw_post_data.
        return self.client.post(url, data,
                                content_type='text/plain',
                                HTTP_X_FILE_NAME=filename)

    def test_attachment_path(self):
        res = self.upload(self.upload_url, 'foo', 'some.txt')
        eq_(res.status_code, 200)
        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=1)
        att = revision.attachments.all()[0]
        bits = att.path.split(os.path.sep)
        now = datetime.now()
        eq_(bits[-4:-1], now.strftime('%Y-%m-%d').split('-'))

    def test_attachment_add_read(self):
        res = self.upload(self.upload_url, 'foo', 'some.txt')
        eq_(res.status_code, 200)

        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=1)
        eq_(revision.attachments.count(), 1)
        eq_(revision.attachments.all()[0].read(), 'foo')

    def test_attachment_add(self):
        res = self.upload(self.upload_url, 'foo', 'some.txt')
        eq_(res.status_code, 200)
        json.loads(res.content)

        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=1)
        eq_(revision.attachments.count(), 1)

    def test_attachment_default_extension(self):
        revision = self.add_one(data='foo', filename='some')
        eq_(revision.attachments.all()[0].ext, 'js')

    def test_attachment_large(self):
        raise SkipTest()
        # A test for large attachments... really slow things
        # down, so before you remove the above, clean this up
        # or drop down the file size limit.
        temp = StringIO.StringIO()
        for x in range(0, 1024 * 32):
            temp.write("x" * 1024)

        self.upload(self.upload_url, temp.getvalue(), 'some-big-file.txt')

    def test_attachment_same_fails(self):
        self.test_attachment_add()
        self.assertRaises(FilenameExistException, self.upload,
                          self.get_upload_url(1), 'foo bar', 'some.txt')

    def test_attachment_revision_count(self):
        revisions = PackageRevision.objects.filter(package=self.package)
        eq_(revisions.count(), 1)
        self.test_attachment_add()
        eq_(revisions.count(), 2)
        # Double check that adding a revision does not create a new version.

    def test_attachment_same_change(self):
        self.test_attachment_add()
        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=1)
        eq_(revision.attachments.count(), 1)

        data = {revision.attachments.all()[0].get_uid: 'foo bar'}
        res = self.client.post(self.get_change_url(1), data)
        eq_(res.status_code, 200)

        eq_(revision.attachments.all()[0].read(), 'foo')

        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=2)
        eq_(revision.attachments.count(), 1)
        eq_(revision.attachments.all()[0].read(), 'foo bar')

    def test_attachment_two_files(self):
        revision = self.add_one()
        assert revision.attachments.count(), 1

        self.upload(self.upload_url, 'foo', 'some-other.txt')
        assert revision.attachments.count(), 2

    def test_attachment_latest(self):
        old = self.add_one()
        old_uid = old.attachments.all()[0].get_uid

        data = {old.attachments.all()[0].get_uid: 'foo bar'}
        self.client.post(self.get_change_url(1), data)

        new = PackageRevision.objects.get(package=self.package,
                                          revision_number=2)
        new_uid = new.attachments.all()[0].get_uid

        eq_(latest_by_uid(old, old_uid).get_uid, new_uid)
        eq_(latest_by_uid(new, old_uid).get_uid, new_uid)
        eq_(latest_by_uid(old, new_uid).get_uid, new_uid)
        eq_(latest_by_uid(new, new_uid).get_uid, new_uid)
        eq_(latest_by_uid(old, 'foofy'), None)

    def test_attachment_old_uid(self):
        revision = self.add_one()

        data = {revision.attachments.all()[0].get_uid: 'foo bar'}
        self.client.post(self.get_change_url(1), data)

        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=2)
        eq_(revision.attachments.count(), 1)

        # Note here we are still sending the old uid, insted of the
        # newer and fancier one.
        data = {revision.attachments.all()[0].get_uid: 'foo bar two'}
        self.client.post(self.get_change_url(2), data)

        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=3)
        eq_(revision.attachments.all()[0].read(), 'foo bar two')

        # Check the old data.
        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=2)
        eq_(revision.attachments.all()[0].read(), 'foo bar')

    def test_attachment_jump_revision(self):
        revision = self.add_one()

        data = {revision.attachments.all()[0].get_uid: 'foo bar'}
        self.client.post(self.get_change_url(1), data)

        data = {revision.attachments.all()[0].get_uid: 'foo bar zero'}
        self.client.post(self.get_change_url(0), data)

        eq_(PackageRevision.objects.filter(package=self.package).count(), 4)
        atts = Attachment.objects.filter(revisions__package=self.package)

        eq_(atts[0].read(), 'foo')
        eq_(atts[1].read(), 'foo bar')
        eq_(atts[2].read(), 'foo bar zero')
        eq_(atts[2].revisions.all()[0].revision_number, 3)

    def test_paths(self):
        revision = self.add_one()

        data = {revision.attachments.all()[0].get_uid: 'foo bar'}
        self.client.post(self.get_change_url(1), data)
        atts = Attachment.objects.filter(revisions__package=self.package)

        assert atts[0].get_file_path().endswith('%s-some.txt' % atts[0].pk)
        assert atts[1].get_file_path().endswith('%s-some.txt' % atts[1].pk)

    def test_attachment_remove(self):
        revision = self.add_one()

        data = {'uid': revision.attachments.all()[0].get_uid}
        self.client.post(self.get_delete_url(1), data)

        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=2)
        assert not revision.attachments.all().count()

    def test_attachment_remove_old(self):
        revision = self.add_one()

        data = {revision.attachments.all()[0].get_uid: 'foo bar'}
        self.client.post(self.get_change_url(1), data)

        # this is now an old uid
        data = {'uid': revision.attachments.all()[0].get_uid}
        self.client.post(self.get_delete_url(2), data)

        revision = PackageRevision.objects.get(package=self.package,
                                               revision_number=3)
        assert not revision.attachments.all().count()

    def test_attachment_extension_too_long(self):
        res = self.post(self.get_add_url(self.revision.revision_number), 'foo', 'file.toolongofanextension')
        eq_(res.status_code, 403)

    def test_attachment_filename_sanitization(self):
        revision = self.add_one(filename='My Photo of j0hnny.jpg')
        att = revision.attachments.all()[0]
        eq_(att.filename, 'My-Photo-of-j0hnny')
        revision.attachment_remove(att)

        revision = self.add_one(filename='^you*()"[]"are-_crazy')
        att = revision.attachments.all()[0]
        eq_(att.filename, '-you-are-_crazy')
        revision.attachment_remove(att)

        revision = self.add_one(filename='"><a href="">test')
        att = revision.attachments.all()[0]
        eq_(att.filename, '-a-href-test')
        revision.attachment_remove(att)

        revision = self.add_one(filename='template.html.js')
        att = revision.attachments.all()[0]
        eq_(att.filename, 'template.html')
        revision.attachment_remove(att)

        revision = self.add_one(filename='image.-png^*(@&#')
        att = revision.attachments.all()[0]
        eq_(att.filename, 'image')
        eq_(att.ext, 'png')
        revision.attachment_remove(att)

        revision = self.add_one(filename='image.<a href=""')
        att = revision.attachments.all()[0]
        eq_(att.filename, 'image')
        eq_(att.ext, 'ahref')
        revision.attachment_remove(att)

class TestModules(TestCase):

    fixtures = ['mozilla_user', 'users', 'core_sdk', 'packages']

    def setUp(self):
        if not os.path.exists(settings.UPLOAD_DIR):
            os.makedirs(settings.UPLOAD_DIR)

        self.author = User.objects.get(username='john')
        self.author.set_password('password')
        self.author.save()

        self.package = self.author.packages_originated.addons()[0:1].get()
        self.revision = self.package.revisions.all()[0]

        self.client.login(username=self.author.username, password='password')

    def add_one(self, filename='tester'):
        self.client.post(self.get_add_url(self.revision.revision_number), { 'filename': filename })
        self.revision = next(self.revision)
        return self.revision

    def get_add_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_add_module', args=args)

    def get_delete_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_remove_module', args=args)

    def test_module_add(self):
        revision = self.add_one('a-module')
        # 1 for main, 1 for added, so 2
        eq_(revision.modules.all().count(), 2)
        eq_(revision.modules.all().order_by('-id')[0].filename, 'a-module')

    def test_module_add_with_extension(self):
        revision = self.add_one('test.js')
        eq_(revision.modules.all().order_by('-id')[0].filename, 'test')

    def test_module_name_sanitization(self):
        revision = self.add_one(filename='A"> <a href="google.com">malicious module')
        eq_(revision.modules.all().order_by('-id')[0].filename, 'A-a-href-google')

        revision = self.add_one(filename='void:myXSSFunction(fd.item)')
        eq_(revision.modules.all().order_by('-id')[0].filename, 'void-myXSSFunction-fd')

class TestEmptyDirs(TestCase):
    fixtures = ['mozilla_user', 'users', 'core_sdk', 'packages']

    def setUp(self):
        if not os.path.exists(settings.UPLOAD_DIR):
            os.makedirs(settings.UPLOAD_DIR)

        self.author = User.objects.get(username='john')
        self.author.set_password('password')
        self.author.save()

        self.package = self.author.packages_originated.addons()[0:1].get()
        self.revision = self.package.revisions.all()[0]

        self.client.login(username=self.author.username, password='password')

    def post(self, url, data):
        return self.client.post(url, data);

    def add_one(self, name='tester', root_dir='l'):
        self.post(self.get_add_url(self.revision.revision_number),
                  { 'name': name, 'root_dir': root_dir })
        self.revision = next(self.revision)
        return self.revision

    def get_add_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_add_folder', args=args)

    def get_delete_url(self, revision):
        args = [self.package.id_number, revision]
        return reverse('jp_addon_revision_remove_folder', args=args)

    def test_add_folder(self):
        res = self.post(self.get_add_url(self.revision.revision_number),
                        { 'name': 'tester', 'root_dir': 'l' })
        eq_(res.status_code, 200)
        json.loads(res.content)

        revision = next(self.revision)
        folder = revision.folders.all()[0]
        eq_(folder.name, 'tester')

    def test_remove_folder(self):
        self.add_one()
        res = self.post(self.get_delete_url(self.revision.revision_number),
                        { 'name': 'tester', 'root_dir': 'l' })
        eq_(res.status_code, 200)
        json.loads(res.content)

        revision = next(self.revision)
        eq_(revision.folders.count(), 0)

    def test_folder_sanitization(self):
        revision = self.add_one(name='A"> <script src="google.com">/m@l!c!ous')
        eq_(revision.folders.all()[0].name, 'A-script-src-googlecom-/m-l-c-ous')
        revision.folder_remove(revision.folders.all()[0])

        revision = self.add_one(name='/absolute///and/triple/')
        eq_(revision.folders.all()[0].name, 'absolute/and/triple')

    def test_attachment_unwanted_duplication(self):
        # https://bugzilla.mozilla.org/show_bug.cgi?id=633939#c2
        # create attachment
        filename = "html/test"
        response = simplejson.loads(
                self.client.post(self.add_url, {
                    "filename": "%s.html" % filename}).content)
        revision1 = self.package.revisions.filter(
                revision_number=response['revision_number']).get()
        eq_(revision1.revision_number, 1)
        att_uid = response['uid']
        # add content to attachment
        content = "some content"
        response = simplejson.loads(
                self.client.post(
                    self.get_change_url(revision1.revision_number),
                    {att_uid: content}
                    ).content)
        revision2 = self.package.revisions.filter(
                revision_number=response['revision_number']).get()
        eq_(revision2.revision_number, 2)
        att = revision2.attachments.filter(filename=filename).get()
        response = self.client.get(reverse('jp_attachment', args=[att.pk]))
        eq_(response.content, content)
        # updating the attachment in revision1
        content2 = "some other content"
        response = simplejson.loads(
                self.client.post(
                    self.get_change_url(revision1.revision_number),
                    {att_uid: content2}
                    ).content)
        revision3 = self.package.revisions.filter(
                revision_number=response['revision_number']).get()
        eq_(revision3.revision_number, 3)
        eq_(revision3.attachments.count(), 1)
        att = revision3.attachments.filter(filename=filename).get()
        eq_(att.read(), content2)
        response = self.client.get(reverse('jp_attachment', args=[att.pk]))
        eq_(response.content, content2)
