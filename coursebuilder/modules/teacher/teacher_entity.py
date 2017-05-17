# Copyright 2016 Mobile CSP Project. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Contains the TeacherEntity and TeacherItemRESTHandler

import datetime
import logging

from google.appengine.ext import db

from common import schema_fields
from common import utils as common_utils

from controllers import utils

from models import entities
from models import models
from models import resources_display
from models import roles
from models import transforms
from models.models import MemcacheManager
from models.models import Student

# In our module
import messages

GLOBAL_DEBUG = False

class TeacherEntity(entities.BaseEntity):

    """A class that represents a persistent database entity of teacher."""
    enrolled_on = db.DateProperty()
    is_enrolled = db.BooleanProperty(indexed=False)
    is_active = db.BooleanProperty(indexed=False)

    user_id = db.StringProperty(indexed=True)
    name = db.StringProperty(indexed=False)
    date = db.DateProperty()
    email = db.StringProperty(indexed=True)
    school = db.TextProperty(indexed=False)

    # Additional field for teachers
    sections = db.TextProperty(indexed=False)

    memcache_key = 'teachers'

    @classmethod
    def get_teachers(cls, allow_cached=True):
        items = MemcacheManager.get(cls.memcache_key)
        if not allow_cached or items is None:
            items = TeacherEntity.all().order('-date').fetch(1000)

            # TODO(psimakov): prepare to exceed 1MB max item size
            # read more here: http://stackoverflow.com
            #   /questions/5081502/memcache-1-mb-limit-in-google-app-engine
            MemcacheManager.set(cls.memcache_key, items)
        return items

    @classmethod
    def make(cls, name, email, school):
        entity = cls()
        entity.name = name
        entity.date = datetime.datetime.now().date()
        entity.enrolled_on = entity.date
        entity.is_enrolled = True
        entity.is_active = True
        entity.email = email
        entity.school = school
        return entity

    def put(self):
        """Do the normal put() and also invalidate memcache."""
        result = super(TeacherEntity, self).put()
        MemcacheManager.delete(self.memcache_key)
        return result

    def delete(self):
        """Do the normal delete() and invalidate memcache."""
        super(TeacherEntity, self).delete()
        MemcacheManager.delete(self.memcache_key)

class TeacherRights(object):
    """Manages view/edit rights for teachers."""

    # The first four of these pertain an admin viewing teachers
    @classmethod
    def can_view(cls, unused_handler):
        return True

    @classmethod
    def can_edit(cls, handler):
        return roles.Roles.is_course_admin(handler.app_context)

    @classmethod
    def can_delete(cls, handler):
        return cls.can_edit(handler)

    @classmethod
    def can_add(cls, handler):
        return cls.can_edit(handler)

    # These next four pertain to a teacher accessing sections

    @classmethod
    def can_view_section(cls, unused_handler):
        return True

    @classmethod
    def can_edit_section(cls, handler):
        return True

    @classmethod
    def can_delete_section(cls, handler):
        return cls.can_edit_section(handler)

    @classmethod
    def can_add_section(cls, handler):
        return cls.can_edit_section(handler)

    @classmethod
    def apply_rights(cls, handler, items):
        """Filter out items that current user can't see."""
        if TeacherRights.can_edit(handler):
            return items

        allowed = []
        for item in items:
            allowed.append(item)

        return allowed

class TeacherItemRESTHandler(utils.BaseRESTHandler):
    """Provides REST API for adding a teacher."""

    URL = '/rest/teacher/item'

    @classmethod
    def SCHEMA(cls):
        """
           SCHEMA used to display Entity form in oeditor.  

           The 'mode' field is used to distinguish between
           adding and editing an Entity.
        """

        schema = schema_fields.FieldRegistry('Teacher',
            extra_schema_dict_values={
                'className': 'inputEx-Group new-form-layout'})
        schema.add_property(schema_fields.SchemaField(
            'key', 'ID', 'string', editable=False, hidden=True))
        schema.add_property(schema_fields.SchemaField(          
            'mode', 'Mode', 'string', editable=False, hidden=True)) 
        schema.add_property(schema_fields.SchemaField(
            'name', 'Name', 'string',
            description=messages.TEACHER_NAME_DESCRIPTION))
        schema.add_property(schema_fields.SchemaField(
            'email', 'Email', 'string',
            description=messages.TEACHER_EMAIL_DESCRIPTION))
        schema.add_property(schema_fields.SchemaField(
            'school', 'School', 'string',
            description=messages.TEACHER_SCHOOL_DESCRIPTION))
        return schema

    def get(self):
        """Handles REST GET verb and returns an object as JSON payload."""
        key = self.request.get('key')

        # The Entity will have been saved already either with or without data.
        try:
            entity = TeacherEntity.get(key)
        except db.BadKeyError:
            entity = None

        if not entity:
            transforms.send_json_response(
                self, 404, 'MobileCSP: Teacher Entity not found.', {'key': key})
            return

        viewable = TeacherRights.apply_rights(self, [entity])
        if not viewable:
            transforms.send_json_response(
                self, 401, 'MobileCSP: Admin access denied.', {'key': key})
            return
        entity = viewable[0]

        schema = TeacherItemRESTHandler.SCHEMA()

        entity_dict = transforms.entity_to_dict(entity)
        if GLOBAL_DEBUG:
            logging.warning('***RAM*** get entity = ' + str(entity_dict))

        # Distinguish between adding a new entity and editing and existing entity
        # If this is a new Entity, it won't have a user_id yet.
        if GLOBAL_DEBUG:
            logging.warning('***RAM*** user_id ' + str(entity_dict['user_id']))
        if entity_dict['user_id'] or entity_dict['email'] != '':
            entity_dict['mode'] = 'Edit'
        else:
            entity_dict['mode'] = 'Add'

        # Format the internal date object as ISO 8601 datetime, with time
        # defaulting to 00:00:00
        date = entity_dict['date']
        date = datetime.datetime(date.year, date.month, date.day)
        entity_dict['date'] = date

        json_payload = transforms.dict_to_json(entity_dict)
        transforms.send_json_response(
            self, 200, 'Success.',
            payload_dict=json_payload,
            xsrf_token=utils.XsrfTokenManager.create_xsrf_token(
                'teacher-put'))

    def put(self):
        """Handles REST PUT verb with JSON payload."""
        request = transforms.loads(self.request.get('request'))
        key = request.get('key')
        edit_mode = request.get('mode')

        if GLOBAL_DEBUG:
            logging.warning('***RAM*** put request = ' + str(request))

        if not self.assert_xsrf_token_or_fail(
                request, 'teacher-put', {'key': key}):
            return

        if not TeacherRights.can_edit(self):
            transforms.send_json_response(
                self, 401, 'MobileCSP: Admin access denied.', {'key': key})
            return

        entity = TeacherEntity.get(key)
        if not entity:
            transforms.send_json_response(
                self, 404, 'MobileCSP: Teacher Entity not found.', {'key': key})
            return

        schema = TeacherItemRESTHandler.SCHEMA()

        payload = request.get('payload')
        update_dict = transforms.json_to_dict(
            transforms.loads(payload), schema.get_json_schema_dict())

        #  Get the teacher's user_id
        user = Student.get_first_by_email(update_dict['email'])[0]  # returns a tuple
        if not user:
            transforms.send_json_response(
                self, 404, 'MobileCSP: No registered user found for ' + update_dict['email'], {'key': key})
            return

        # Check that the teacher isn't already registered
        if update_dict['mode'] == 'Add':
            teachers = TeacherEntity.get_teachers()
            for teacher in teachers:
                if teacher.email == update_dict['email']:
                    transforms.send_json_response(
                        self, 404, 'MobileCSP: User is already registered as a teacher ' + update_dict['email'], {'key': key})
                    return

        if GLOBAL_DEBUG:
            logging.debug('****RAM**** teacher id ' + str(user.user_id))

        # Store the user_id
        update_dict['user_id'] = user.user_id

        transforms.dict_to_entity(entity, update_dict)

        entity.put()

        transforms.send_json_response(self, 200, 'Saved.')

    def delete(self):
        """Deletes an teacher."""
        key = self.request.get('key')

        if not self.assert_xsrf_token_or_fail(
                self.request, 'teacher-delete', {'key': key}):
            return

        if not TeacherRights.can_delete(self):
            self.error(401)
            return

        entity = TeacherEntity.get(key)
        if not entity:
            transforms.send_json_response(
                self, 404, 'MobileCSP: Teacher Entity not found.', {'key': key})
            return

        entity.delete()

        transforms.send_json_response(self, 200, 'Deleted.')


