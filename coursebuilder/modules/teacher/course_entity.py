# Copyright 2016 Mobile CSP Project All rights Reserved.
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

__author__ = 'barok.imana@trincoll.edu'
__author__ = 'ram8647@trincoll.edu'

import datetime
import logging
import re 

from google.appengine.ext import db
from google.appengine.api import users

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
from teacher_entity import TeacherRights

GLOBAL_DEBUG = False

class CourseSectionEntity(entities.BaseEntity):

    """Course section information"""
    name = db.StringProperty(indexed=False)
    acadyr = db.StringProperty(indexed=False)
    description = db.StringProperty(indexed=False)
    is_active = db.BooleanProperty(indexed=False)
    date = db.DateProperty()
    students = db.TextProperty(indexed=False)
    teacher_email = db.TextProperty(indexed=False)
    section_id = db.StringProperty(indexed=True)    
    labels = db.StringProperty(indexed=False)

    memcache_key = 'sections'

    @classmethod
    def get_sections(cls, allow_cached=True):
        sections = MemcacheManager.get(cls.memcache_key)
        if not allow_cached or sections is None:
            sections = CourseSectionEntity.all().order('-date').fetch(1000)
            MemcacheManager.set(cls.memcache_key, sections)
        return sections

    @classmethod
    def make(cls, name, acadyr, description, is_active):
        entity = cls()
        entity.name = name
        entity.acadyr = acadyr
        entity.description = description
        entity.is_active = is_active
        entity.date = datetime.datetime.now().date()
        entity.teacher_email = users.get_current_user().email()
        entity.students = ""
        return entity

    def put(self):
        """Do the normal put() and also invalidate memcache."""
        result = super(CourseSectionEntity, self).put()
        MemcacheManager.delete(self.memcache_key)
        return result

    def delete(self):
        """Do the normal delete() and invalidate memcache."""
        super(CourseSectionEntity, self).delete()
        MemcacheManager.delete(self.memcache_key)

class SectionItemRESTHandler(utils.BaseRESTHandler):
    """Provides REST API for adding a section."""

    URL = '/rest/section/item'

    @classmethod
    def SCHEMA(cls):
        schema = schema_fields.FieldRegistry('Section Editor',
            extra_schema_dict_values={
                'className': 'inputEx-Group new-form-layout'})
        schema.add_property(schema_fields.SchemaField(
            'key', 'ID', 'string', editable=False, hidden=True))
        schema.add_property(schema_fields.SchemaField(
            'mode', 'Mode', 'string', editable=False, hidden=True))
        schema.add_property(schema_fields.SchemaField(
            'directions', 'Directions', 'string',
            editable=False, optional=True,
            default_value='Here is what to do.'))
        schema.add_property(schema_fields.SchemaField(
            'name', 'Name', 'string',
        ))
        schema.add_property(schema_fields.SchemaField(
            'acadyr', 'Academic Year', 'string',
            select_data=[
                 ('2016-17', '2016-17'),
                 ('2017-18', '2017-18'),
                 ('2018-19', '2018-19'),
                 ('2019-20', '2019-20')]))

        schema.add_property(schema_fields.SchemaField(
            'description', 'Optional Description', 'string',
            optional=True))
        schema.add_property(schema_fields.SchemaField(
            'students', 'Class Roster', 'text',
            description=messages.SECTION_STUDENTS_DESCRIPTION,
            optional=True))
        return schema

    def get(self):
        """Handles REST GET verb and returns an object as JSON payload."""
        key = self.request.get('key')

        try:
            entity = CourseSectionEntity.get(key)
        except db.BadKeyError:
            entity = None

        if not entity:
            transforms.send_json_response(
                self, 404, 'MobileCSP: Course Section not found.', {'key': key})
            return

        viewable = TeacherRights.apply_rights(self, [entity])
        if not viewable:
            transforms.send_json_response(
                self, 401, 'MobileCSP: Access denied.', {'key': key})
            return
        entity = viewable[0]

        schema = SectionItemRESTHandler.SCHEMA()

        entity_dict = transforms.entity_to_dict(entity)
        if GLOBAL_DEBUG:
            logging.warning('***RAM*** get entity = ' + str(entity_dict))

        # Distinguish between adding a new entity and editing an existing entity
        # If this is a new Entity, its acadyr field will be blank.
        if entity_dict['acadyr'] != '':
            entity_dict['mode'] = 'Edit'
        else:
            entity_dict['mode'] = 'Add'

        # Format the internal date object as ISO 8601 datetime, with time
        # defaulting to 00:00:00
        date = entity_dict['date']
        date = datetime.datetime(date.year, date.month, date.day)
        entity_dict['date'] = date
        
        emails = entity_dict['students']   # Student emails are comma-delimited
        emails = emails.replace(',', '\n') # Replace with new lines for display
        entity_dict['students'] = emails

        if entity_dict['mode'] == 'Edit':
            entity_dict['directions'] = "Edit a section: To add or delete students, add (or remove) their emails to (or from) the Class Roster."
        else:
           entity_dict['name'] = "New section"
           entity_dict['directions'] = "New section: Give the section a name and (optionally) a short description and pick an academic year. " + \
               "To create a roster of students, you must use the exact email that the student is registered under. Put one email per line or " + \
               "separate emails by commas."

        entity_dict.update(
            resources_display.LabelGroupsHelper.labels_to_field_data(
                common_utils.text_to_list(entity.labels)))

        json_payload = transforms.dict_to_json(entity_dict)
        transforms.send_json_response(
            self, 200, 'Success.',
            payload_dict=json_payload,
            xsrf_token=utils.XsrfTokenManager.create_xsrf_token(
                'section-put'))

    def put(self):
        """Handles REST PUT verb with JSON payload."""
 
        request = transforms.loads(self.request.get('request'))
        key = request.get('key')

        if not self.assert_xsrf_token_or_fail(
                request, 'section-put', {'key': key}):
#            logging.warning('***RAM*** put FAIL (saving) ' + str(request))
            return

#        logging.warning('***RAM*** put (saving) ' + str(request))

        if not TeacherRights.can_edit_section(self):
            transforms.send_json_response(
                self, 401, 'MobileCSP: Access denied.', {'key': key})
            return

        entity = CourseSectionEntity.get(key)
        if not entity:
            transforms.send_json_response(
                self, 404, 'MobileCSP: Course Section not found.', {'key': key})
            return

        schema = SectionItemRESTHandler.SCHEMA()

        payload = request.get('payload')
        update_dict = transforms.json_to_dict(
            transforms.loads(payload), schema.get_json_schema_dict())

        # Check for invalid emails -- email must be a registered student
        # Found the regular expression on Stackoverflow
        emails_raw = update_dict['students']
        emails = re.findall(r'[\w\.-]+@[\w\.-]+', emails_raw)
        
        return_code = 200
        bad_emails = []
        good_emails = []
        for email in emails:
#            email = email.strip(' \t\n\r')
            if email:
                logging.debug('***RAM*** email = |' + email + '|')
                student = Student.get_first_by_email(email)[0]  # returns a tuple
                if not student:
                    bad_emails.append(email)
                else:
                    good_emails.append(email)
     
        confirm_message  = 'Confirmation\n'
        confirm_message += '------------\n\n' 
        if bad_emails:
            logging.info('***RAM*** bad_emails found = ' + str(bad_emails))
            return_code = 401
            confirm_message = 'The following were invalid emails:\n'
            for email in bad_emails: 
                confirm_message += email + '\n'
            confirm_message += 'Either there is no student with that email\n'
            confirm_message += 'registered for the course.  Or there is a \n'
            confirm_message += 'typo in the email address provided.\n\n'
        if good_emails:
            logging.info('***RAM*** good_emails found = ' + str(good_emails))
            confirm_message += 'Students with the following emails\n'
            confirm_message += 'are currently registered in your section:\n'
            for email in good_emails:
                confirm_message += email + '\n'
          
            update_dict['students'] = ','.join(good_emails)  # New-line delimited

        transforms.dict_to_entity(entity, update_dict)

        entity.put()
        if return_code == 200:
            confirm_message += 'Your section was successfully updated and saved.\n\n\n\n\n'
        else:
            confirm_message += 'Other information for your section was successfully updated and saved.\n\n\n\n\n'
        confirm_message += 'Confirmation\n'
        confirm_message += '------------\n'

        transforms.send_json_response(
            self, return_code, confirm_message, {'key': key})

    def delete(self):
        """Deletes a section."""
        key = self.request.get('key')

        if not self.assert_xsrf_token_or_fail(
                self.request, 'section-delete', {'key': key}):
            return

        if not TeacherRights.can_delete_section(self):
            self.error(401)
            return

        entity = CourseSectionEntity.get(key)
        if not entity:
            transforms.send_json_response(
                self, 404, 'MobileCSP: Course Section not found.', {'key': key})
            return

        entity.delete()

        transforms.send_json_response(self, 200, 'Deleted.')
