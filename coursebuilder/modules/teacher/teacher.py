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

""" Classes and methods to create and manage the Teacher Dashboard.
    Based off of the announcements module, which was created by 
    saifu@google.com.   
"""

__author__ = 'Saifu Angto (saifu@google.com)'
__author__ = 'ehiller@css.edu'
__author__ = 'Ralph Morelli (ram8647@gmail.com)'

import cgi
import datetime
import os
import urllib
import logging

import jinja2

import appengine_config
from common import tags
from common import utils as common_utils
from common import schema_fields
from common import jinja_utils
from controllers import utils
from models import resources_display
from models import custom_modules
from models import entities
from models import models
from models import roles
from models import transforms
from models import utils as models_utils
from models.models import MemcacheManager
from models.models import Student
from models.models import EventEntity
from modules.teacher import messages
from modules.dashboard import dashboard
from modules.oeditor import oeditor

from google.appengine.ext import db
from google.appengine.api import users

# Our modules classes
from course_entity import CourseSectionEntity
from course_entity import SectionItemRESTHandler
from teacher_entity import TeacherEntity
from teacher_entity import TeacherItemRESTHandler
from teacher_entity import TeacherRights
from student_activites import ActivityScoreParser
from student_answers import StudentAnswersEntity

GLOBAL_DEBUG = False

MODULE_NAME = 'teacher'
MODULE_TITLE = 'Teacher Dashboard'

#Setup paths and directories for templates and resources
RESOURCES_PATH = '/modules/teacher/resources'
TEMPLATE_DIR = os.path.join(
    appengine_config.BUNDLE_ROOT, 'modules', MODULE_NAME, 'templates')

# These are the module's templates.  The first is the teacher's splash page.
TEACHERS_TEMPLATE = os.path.join(TEMPLATE_DIR, 'teacher_dashboard.html')
STUDENT_ROSTER_TEMPLATE = os.path.join(TEMPLATE_DIR, 'student_roster.html')
STUDENT_DASHBOARD_TEMPLATE = os.path.join(TEMPLATE_DIR, 'student_dashboard.html')
QUESTION_PREVIEW_TEMPLATE = os.path.join(TEMPLATE_DIR, 'question_preview.html')

class TeacherHandlerMixin(object):
    def get_admin_action_url(self, action, key=None):
        args = {'action': action}
        if key:
            args['key'] = key
        return self.canonicalize_url(
            '{}?{}'.format(
                AdminDashboardHandler.URL, urllib.urlencode(args)))

    def get_dashboard_action_url(self, action, key=None):
        args = {'action': action}
        if key:
            args['key'] = key
        return self.canonicalize_url(
            '{}?{}'.format(
                TeacherDashboardHandler.DASHBOARD_URL, urllib.urlencode(args)))

    def format_admin_template(self, items):
        """ Formats the template for the Admin 'Add Teacher' page.

            When clicked the 'Admin: Add Teacher button opens up 
            a list of teachers plus and 'Add Teacher' button.
        """
        template_items = []
        for item in items:
            item = transforms.entity_to_dict(item)
            date = item.get('date')
            if date:
                date = datetime.datetime.combine(
                    date, datetime.time(0, 0, 0, 0))
                item['date'] = (
                    date - datetime.datetime(1970, 1, 1)).total_seconds() * 1000

            # add 'edit' actions
            if TeacherRights.can_edit_section(self):
                item['edit_action'] = self.get_admin_action_url(
                     AdminDashboardHandler.ADMIN_EDIT_ACTION, key=item['key'])
                item['delete_xsrf_token'] = self.create_xsrf_token(
                    AdminDashboardHandler.ADMIN_DELETE_ACTION)
                item['delete_action'] = self.get_admin_action_url(
                    AdminDashboardHandler.ADMIN_DELETE_ACTION,
                    key=item['key'])

            template_items.append(item)

        output = {}
        output['children'] = template_items

        # Add actions for the 'Add Teacher'
        if TeacherRights.can_edit(self):
            output['add_xsrf_token'] = self.create_xsrf_token(
                AdminDashboardHandler.ADMIN_ADD_ACTION)
            output['add_action'] = self.get_admin_action_url(
                AdminDashboardHandler.ADMIN_ADD_ACTION)

        return output

    def format_dashboard_template(self, sections, user_email):
        """ Formats the template for the main Teacher Dashboard page.

            This is the page that registered teachers will see.  It consists of
            list of the teacher's course sections and buttons to manage the
            sections. 
        """
        template_sections = []
        if sections:
            for section in sections:
                section = transforms.entity_to_dict(section)
                date = section.get('date')
                if date:
                    date = datetime.datetime.combine(
                        date, datetime.time(0, 0, 0, 0))
                    section['date'] = (
                        date - datetime.datetime(1970, 1, 1)).total_seconds() * 1000

                if GLOBAL_DEBUG:
                    logging.debug('***RAM*** format template section = ' + str(section))

                # Add 'edit' and 'delete' actions to each section that will be displayed

                if section['teacher_email'] == user_email and TeacherRights.can_edit_section(self):
                    section['edit_action'] = self.get_dashboard_action_url(
                        TeacherDashboardHandler.EDIT_SECTION_ACTION, key=section['key'])

                    section['delete_xsrf_token'] = self.create_xsrf_token(
                        TeacherDashboardHandler.DELETE_SECTION_ACTION)
                    section['delete_action'] = self.get_dashboard_action_url(
                        TeacherDashboardHandler.DELETE_SECTION_ACTION,
                        key=section['key'])
                    template_sections.append(section) 

        output = {}
        output['sections'] = template_sections

        # Add actions for the 'New Section' button
        output['newsection_xsrf_token'] = self.create_xsrf_token(
            TeacherDashboardHandler.ADD_SECTION_ACTION)
        output['add_section'] = self.get_dashboard_action_url(
            TeacherDashboardHandler.ADD_SECTION_ACTION)

        # Add actions of the 'Admin' button -- to add new teachers
        if TeacherRights.can_edit(self):
            output['is_admin'] = True
            output['add_xsrf_token'] = self.create_xsrf_token(
                AdminDashboardHandler.ADMIN_LIST_ACTION)
            output['add_action'] = self.get_admin_action_url(
                AdminDashboardHandler.ADMIN_LIST_ACTION)
        return output

class TeacherDashboardHandler(
        TeacherHandlerMixin, utils.BaseHandler,
        utils.ReflectiveRequestHandler):

    """  Handle all Teacher (non-Admin) functions for the Teacher Dashboard.

         The Teacher functions include creating and deleting course sections,
         adding and removing students from sections, and monitoring student
         performance. The Admin functions consist solely of registering teachers
         and are handled by AdminDashboardHandler.
    """

    # Actions for the various Section functions
    LIST_SECTION_ACTION = 'edit_sections'
    EDIT_SECTION_ACTION = 'edit_section'
    DELETE_SECTION_ACTION = 'delete_section'
    ADD_SECTION_ACTION = 'add_section'
    DISPLAY_ROSTER_ACTION = 'display_roster'
    STUDENT_DASHBOARD_ACTION = 'student_dashboard'
    PREVIEW_QUESTION = 'question_preview'

    # The links for Teacher functions
    DASHBOARD_LINK_URL = 'teacher'
    DASHBOARD_URL = '/{}'.format(DASHBOARD_LINK_URL)
    DASHBOARD_LIST_URL = '{}?action={}'.format(DASHBOARD_LINK_URL, LIST_SECTION_ACTION)

    # Not sure what these do?  May be expendable?
    default_action = 'edit_sections'
    get_actions = [default_action, LIST_SECTION_ACTION, EDIT_SECTION_ACTION, 
                   ADD_SECTION_ACTION, DISPLAY_ROSTER_ACTION, STUDENT_DASHBOARD_ACTION, PREVIEW_QUESTION]
    post_actions = [DELETE_SECTION_ACTION]

    def is_registered_teacher(self, user_email):
        """Determines if current user is a registered teacher."""

        items = TeacherEntity.get_teachers()
        items = TeacherRights.apply_rights(self, items)
        for teacher in items:
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** teacher = ' + str(teacher.email))
                logging.debug('***RAM*** user ' + str(user_email))
            if teacher.email == user_email:
                return True
        return False
    
    def _render(self):
        """ Renders the TEACHERS_TEMPLATE by calling super.render(template)

            This assumes that the template's values are in template_value.
        """
        self.template_value['navbar'] = {'teacher': True}
        self.render(TEACHERS_TEMPLATE)

    def _render_roster(self):
        """ Renders the STUDENT_ROSTER_TEMPLATE by calling super.render(template)

            This assumes that the template's values are in template_value.
        """
        self.template_value['navbar'] = {'teacher': True}
        self.render(STUDENT_ROSTER_TEMPLATE)

    def _render_student_dashboard(self):
        """ Renders the STUDENT_DASHBOARD_TEMPLATE by calling super.render(template)

            This assumes that the template's values are in template_value.
        """
        self.template_value['navbar'] = {'teacher': True}
        self.render(STUDENT_DASHBOARD_TEMPLATE)

    def render_page(self, template):
        """ Renders the template that's supplied as an argument."""

        self.template_value['navbar'] = {'teacher': True}
        self.render(template)

    
    def get_question_preview(self):
        """
            Provides a preview of quiz questions. 

            Invoked from student_dashboard.  The question is displayed in a modal
            window that is initialized in modal-window.js.

            This is an adaptation of the question_preview used by the dashboard module.
            It supports Quizly questions.
        """

        self.template_value['navbar'] = {'teacher': True}
        self.template_value['resources_path'] = RESOURCES_PATH
        url = self.request.get('url')
        if url ==  '':
            self.template_value['question'] = tags.html_to_safe_dom(
                '<question quid="{}">'.format(self.request.get('quid')), self)
        else:
            self.template_value['url'] = url
            self.template_value['question'] = 'Quizly'
        self.render(QUESTION_PREVIEW_TEMPLATE)

    def get_edit_sections(self):
        """ Displays a list of this teacher's sections, using the TEACHERS_TEMPLATE.

            This callback method automatically handles 'edit_sections' actions and must be
            named 'get_edit_sections'.

            This action displays the splash page for the Teacher Dashboard. It
            displays when the user clicks on the navbar 'Teachers' tab. From there
            the Teacher can manage all their sections.   It also contains an
            'Admin: Add Teacher' button, which is visible only to admin users.
            Its action is handled by AdminDashboardHandler.

            The template is injected with a list of this teacher's sections.
        """
        # Make sure the user is registered and a registered teacher
        # If not redirect to main course page
        alerts = []
        user_email = ''
        disable = False
        if not users.get_current_user():
            alerts.append('Access denied. Only registered teachers can use this feature.')
            disable = True
        else:        
            user_email = users.get_current_user().email()
            if not self.is_registered_teacher(user_email):
                alerts.append('Access denied. Please see a course admin.')
                disable = True

        if disable:
            self.redirect('/course')
        else:
            sections = CourseSectionEntity.get_sections()
            sections = TeacherRights.apply_rights(self, sections)

            if GLOBAL_DEBUG:
                logging.debug('***RAM*** Trace: get_edit_sections')

            # self._render will render the SECTIONS template
            self.template_value['teacher'] = self.format_dashboard_template(sections, user_email)
            self.template_value['teacher_email'] = user_email
            self.template_value['alerts'] = alerts      # Not really used anymore
            self.template_value['disabled'] = disable   # Not really used anymore
            self._render()

    def get_add_section(self):
        """ Shows an editor for a section entity.

            This callback method is triggered when the user clicks on the 
            'Create New Section' button in the Teacher splach page.
        """
        if not TeacherRights.can_add_section(self):
            self.error(401)
            return

        if GLOBAL_DEBUG: 
            logging.debug('***RAM** get_add_section')
        entity = CourseSectionEntity.make('', '', '', True)
        entity.put()

        self.redirect(self.get_dashboard_action_url(
            self.EDIT_SECTION_ACTION, key=entity.key()))

    def get_edit_section(self):
        """Shows an editor for a section."""

        key = self.request.get('key')

        schema = SectionItemRESTHandler.SCHEMA()

        exit_url = self.canonicalize_url('/{}'.format(self.DASHBOARD_LIST_URL))
        rest_url = self.canonicalize_url('/rest/section/item')
        form_html = oeditor.ObjectEditor.get_html_for(
            self,
            schema.get_json_schema(),
            schema.get_schema_dict(),
            key, rest_url, exit_url,
            delete_method='delete',
            delete_message='Are you sure you want to delete this section?',
            delete_url=self._get_delete_url(
                SectionItemRESTHandler.URL, key, 'section-delete'),
            display_types=schema.get_display_types())

        if GLOBAL_DEBUG:
            logging.debug('***RAM** get_edit_section rendering page')
        self.template_value['main_content'] = form_html;
        self._render()

    def post_delete_section(self):
        """Deletes a section."""
        if not TeacherRights.can_delete_section(self):
            self.error(401)
            return

        if GLOBAL_DEBUG:
            logging.debug('***RAM** post_delete_section')
        key = self.request.get('key')
        entity = CourseSectionEntity.get(key)
        if entity:
            entity.delete()
        self.redirect('/{}'.format(self.DASHBOARD_LIST_URL))

    def _get_delete_url(self, base_url, key, xsrf_token_name):
        return '%s?%s' % (
            self.canonicalize_url(base_url),
            urllib.urlencode({
                'key': key,
                'xsrf_token': cgi.escape(
                    self.create_xsrf_token(xsrf_token_name)),
            }))

    def get_lessons_for_roster(self, units, course):
        lessons = {}
        for unit in units:
            unit_lessons = course.get_lessons(unit.unit_id)
            unit_lessons_filtered = []
            for lesson in unit_lessons:
                unit_lessons_filtered.append({
                    'title': lesson.title,
                    'unit_id': lesson.unit_id,
                    'lesson_id': lesson.lesson_id
                })
            lessons[unit.unit_id] = unit_lessons_filtered
        
        # Convert to JSON
        return transforms.dumps(lessons, {}) 

    def calculate_lessons_progress(self, lessons_progress):
        """ Returns a dict summarizing student progress on the lessons in each unit."""

        if GLOBAL_DEBUG:
            logging.debug('***RAM*** lessons_progress ' + str(lessons_progress))
        lessons = {}
        total = 0
        for key in lessons_progress:
            progress = lessons_progress[key]['html']
            if  progress == 2:  # 2=complete, 1= inprogress, 0=unstarted
                total += 1
            lessons[str(key)] = progress
        if len(lessons) > 0:
            lessons['progress'] = str(round(total / len(lessons) * 100, 2))
        else:
            lessons['progress'] = str(0)
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** calc lessons = ' + str(lessons))
        return lessons
                            
    def calculate_student_progress_data(self, student, course, tracker, units):
        """ Returns a dict that summarizes student progress for course, units, and lessons.

           The dict takes the form: {'course_progress': c, 'unit_completion': u, 'lessons_progress': p}
           where 'course_progress' is a number giving the overall percentage of lessons completed
           as calculated by GCB, 'unit_completion' gives the completion percentage of each unit, 
           as calculated by GCB, and 'lessons_progress', gives a summary of the lesson progress
           for each unit, as calculated by us.
        """

        # Progress on each unit in the course -- an unitid index dict
        unit_progress_raw = tracker.get_unit_percent_complete(student)
        unit_progress_data = {}
        for key in unit_progress_raw:
            unit_progress_data[str(key)] = str(round(unit_progress_raw[key] * 100,2));
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** unit_progress_data ' + str(unit_progress_data))

        # An object that summarizes student progress
        student_progress = tracker.get_or_create_progress(student)
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** student_progress ' + str(student_progress))

        # Overall progress in the course -- a per cent, rounded to 3 digits
        course_progress = 0
        for value in unit_progress_raw.values():
            course_progress += value
        course_progress = str(round(course_progress / len(unit_progress_data) * 100,2))

        # Progress on each lesson in the coure -- a tuple-index dict:  dict[(unitid,lessonid)] 
        units_lessons_progress = {}
        for unit in units:
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** unit = ' + str(unit.unit_id))
            # Don't show assessments that are part of unit
            if course.get_parent_unit(unit.unit_id):
                continue
            if unit.unit_id in unit_progress_raw:
                lessons_progress = tracker.get_lesson_progress(student, unit.unit_id, student_progress)
                if GLOBAL_DEBUG:
                    logging.debug('***RAM*** lesson_status = ' + str(lessons_progress))
                units_lessons_progress[str(unit.unit_id)] = self.calculate_lessons_progress(lessons_progress)
        return {'unit_completion':unit_progress_data, 'course_progress':course_progress, 'lessons_progress': units_lessons_progress }

    def retrieve_student_scores_and_attempts(self, student_email, course):
        scores = {}

        student = Student.get_first_by_email(student_email)[0]  # returns a tuple

        scores = ActivityScoreParser.get_activity_scores([student.user_id], course, True)
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** get activity scores ' + str(scores))
      
        return scores

    def calculate_performance_ratio(self, aggregate_scores, email): 
        if email not in aggregate_scores.keys():
            return aggregate_scores         
        scores = aggregate_scores[email]
        for unit in scores:
            for lesson in scores[unit]:
                n_questions = 0
                n_correct = 0
                for quest in scores[unit][lesson]:
                    n_questions += 1
                    n_correct += scores[unit][lesson][quest]['score']
                scores[unit][lesson]['ratio'] = str(n_correct) + "/" + str(n_questions)
        return scores

    def create_student_table(self, email, course, tracker, units, get_scores=False):
        student_dict = {}
        student = Student.get_first_by_email(email)[0]  # returns a tuple
        if student:
            progress_dict = self.calculate_student_progress_data(student,course,tracker,units)
            if get_scores:
                scores = self.retrieve_student_scores_and_attempts(email, course)
                student_dict['attempts'] = scores['attempts']
#                    student_dict['scores'] = scores['scores']
                student_dict['scores'] = self.calculate_performance_ratio(scores['scores'], email)
            student_dict['name'] = student.name
            student_dict['email'] = student.email
            student_dict['progress_dict'] = progress_dict
            student_dict['has_scores'] = get_scores
        return student_dict

    def create_student_data_table(self, course, section, tracker, units, student_email = None):
        """ Creates a lookup table containing all student progress data 
            for every unit, lesson, and quiz. 
        """
        # If called from get_student_dashboad to get stats for a single student
        if student_email:
            return self.create_student_table(student_email, course, tracker, units, get_scores=True)

        if section.students:
            index = section.students.split(',')   # comma-delimited emails
        else:
            index = []

        if GLOBAL_DEBUG:
            logging.debug('***RAM*** students index : ' + str(index))

        students = []
        if len(index) > 0:
            for email in index:
                student_dict = self.create_student_table(email, course, tracker, units, get_scores=False)
                if student_dict:
                    students.append(student_dict)
        return students

    def get_display_roster(self):
        """Callback method to display the Roster view. 

           This is called when the user clicks on the 'View Roster' button  
           from the main Teacher Dashboard page.  It displays all students 
           in a single course section and their progress in the course.
           Also allows the teacher to manage the section.
        """
        key = self.request.get('key')
        course_section = CourseSectionEntity.get(key)

        # Get a progress tracker for the course
        this_course = self.get_course()
        tracker = this_course.get_progress_tracker()

        # Get this course's units
        units = this_course.get_units()
        units_filtered = filter(lambda x: x.type == 'U', units) #filter out assessments

        # And lessons
        lessons = self.get_lessons_for_roster(units_filtered, this_course)

        # Get students and progress data for this section 
        students = self.create_student_data_table(this_course, course_section, tracker, units_filtered)

        if GLOBAL_DEBUG:
            logging.debug('***RAM*** Units  : ' + str(units_filtered))
            logging.debug('***RAM*** Lessons : ' + str(lessons))
            logging.debug('***RAM*** Students : ' + str(students))

        user_email = users.get_current_user().email()
        self.template_value['resources_path'] = RESOURCES_PATH
        self.template_value['section'] = { 'key': key, 'teacher': user_email, 'name' : course_section.name, 'description' : course_section.description }
        self.template_value['units'] = units_filtered
        self.template_value['lessons'] = lessons 
        self.template_value['students'] = students
        self.template_value['students_json'] = transforms.dumps(students, {})  # for use with javascript

        self._render_roster()

    def get_student_dashboard(self):
        """Callback method to display details of the student performance. 

           This is called when the user clicks on the 'View Dashboard' button  
           from the Section Roster page.  It displays details for all
           units and lessons.
        """
        student_email = self.request.get('student')
        this_course = self.get_course()
        tracker = this_course.get_progress_tracker()

        # Get this course's units
        units = this_course.get_units()
        units_filtered = filter(lambda x: x.type == 'U', units) #filter out assessments

        self.template_value['student_email'] = student_email
        self.template_value['units'] = units_filtered
        self.template_value['lessons'] =  self.get_lessons_for_roster(units_filtered, this_course)
        student_dict = self.create_student_data_table(this_course, None, tracker, units_filtered, student_email)
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** Student : ' + str(student_dict))
        self.template_value['student'] = student_dict
        self.template_value['studentJs'] = transforms.dumps(student_dict, {}) # for use with javascript
       
       
        self._render_student_dashboard()

class AdminDashboardHandler(TeacherHandlerMixin, dashboard.DashboardHandler):

    """ Handler for all Admin functions, which basically consists of giving teachers
        access to the Teacher Dashboard.

        This is a subclass of DashboardHandler, so it comes with functionality that
        is available to other Handlers, mainly in how pages are rendered.
        DashboardHandler has a render_page method that is not available in other
        handlers.
    """

    # The various Admin Actions
    ADMIN_LIST_ACTION = 'edit_teachers'
    ADMIN_EDIT_ACTION = 'edit_teacher'
    ADMIN_DELETE_ACTION = 'delete_teacher'
    ADMIN_ADD_ACTION = 'add_teacher'

    # Not sure what these do?
    get_actions = [ADMIN_EDIT_ACTION, ADMIN_LIST_ACTION]
    post_actions = [ADMIN_ADD_ACTION, ADMIN_DELETE_ACTION]

    ADMIN_LINK_URL = 'mcsp_admin'
    URL = '/{}'.format(ADMIN_LINK_URL)
    ADMIN_LIST_URL = '{}?action={}'.format(ADMIN_LINK_URL, ADMIN_LIST_ACTION)

    @classmethod
    def get_child_routes(cls):

        """ Add child handlers for REST. The REST handlers perform
            retrieve and store teachers, sections, and other data
            used by the Teacher Dashboard.
        """

        if GLOBAL_DEBUG:
            logging.debug('***RAM** get_child_routes')
        return [
            (TeacherItemRESTHandler.URL, TeacherItemRESTHandler),
            (SectionItemRESTHandler.URL, SectionItemRESTHandler)
            ]

    def get_edit_teachers(self):

        """ Displays a list of registered teachers.

            This is the splash page for Admin users of Teacher Dashboard.
            It is reached by clicking the 'Admin: Add Teacher' button in
            the Teacher Dashboard splash page.  From this page Admins can
            perform all tasks associated with registering teachers.
        """

        items = TeacherEntity.get_teachers()
        items = TeacherRights.apply_rights(self, items)

        if GLOBAL_DEBUG:
            logging.debug('***RAM**  Trace: get_edit_teachers')
        main_content = self.get_template(
            'mcsp_admin_dashboard.html', [TEMPLATE_DIR]).render({
                'teachers': self.format_admin_template(items),
            })

        self.render_page({
            'page_title': self.format_title('Teachers'),
            'main_content': jinja2.utils.Markup(main_content)})

    def get_edit_teacher(self):
        """Shows an editor for a teacher."""

        key = self.request.get('key')

        schema = TeacherItemRESTHandler.SCHEMA()

        exit_url = self.canonicalize_url('/{}'.format(self.ADMIN_LIST_URL))
        rest_url = self.canonicalize_url('/rest/teacher/item')
        form_html = oeditor.ObjectEditor.get_html_for(
            self,
            schema.get_json_schema(),
            schema.get_schema_dict(),
            key, rest_url, exit_url,
            delete_method='delete',
            delete_message='Are you sure you want to delete this teacher?',
            delete_url=self._get_delete_url(
                TeacherItemRESTHandler.URL, key, 'teacher-delete'),
            display_types=schema.get_display_types())

        if GLOBAL_DEBUG:
            logging.debug('***RAM** get_edit_teacher rendering page')
        self.render_page({
            'main_content': form_html,
            'page_title': 'Edit Teacher',
        }, in_action=self.ADMIN_LIST_ACTION)

    def post_delete_teacher(self):
        """Deletes an teacher."""
        if not TeacherRights.can_delete(self):
            self.error(401)
            return

        if GLOBAL_DEBUG:
            logging.debug('***RAM** post_delete_teacher')
        key = self.request.get('key')
        entity = TeacherEntity.get(key)
        if entity:
            entity.delete()
        self.redirect('/{}'.format(self.ADMIN_LIST_URL))

    def post_add_teacher(self):
        """Adds a new teacher and redirects to an editor for it."""
        if not TeacherRights.can_add(self):
            self.error(401)
            return

        if GLOBAL_DEBUG:
            logging.debug('***RAM** post_add_teacher')
        entity = TeacherEntity.make('', '', '')
        entity.put()

        self.redirect(self.get_admin_action_url(
            self.ADMIN_EDIT_ACTION, key=entity.key()))

    def _get_delete_url(self, base_url, key, xsrf_token_name):
        return '%s?%s' % (
            self.canonicalize_url(base_url),
            urllib.urlencode({
                'key': key,
                'xsrf_token': cgi.escape(
                    self.create_xsrf_token(xsrf_token_name)),
            }))



def record_tag_assessment(source, user, data):
    """ Callback function when student attempts a quiz question.

        A tag-assessment event is a submittal of an answer
        for a lesson question or quizly exercise.  The data
        dict has some of the information that is needed to
        construct a performance profile on these answers for
        this user.
    """

    if source == 'tag-assessment':
        StudentAnswersEntity.record(user, data)
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** data = ' + str(data))

def notify_module_enabled():
    """Handles things after module has been enabled.

       Adding an event listener to EventEntity lets us record
       student activity on questions and quizly exercises in
       our own database as they occur.

       TODO: Try to measure the cost of storing this extra
       data.
    """
    EventEntity.EVENT_LISTENERS.append(record_tag_assessment)

custom_module = None


def register_module():
    """Registers this module in the registry."""

    handlers = [
        (AdminDashboardHandler.URL, AdminDashboardHandler),
        (TeacherDashboardHandler.DASHBOARD_URL, TeacherDashboardHandler)
    ]

    # These are necessary to access the js and css resources.
    global_routes = [
      (RESOURCES_PATH + '/js/modal-window.js', tags.ResourcesHandler),
      (RESOURCES_PATH + '/js/tipped.js', tags.ResourcesHandler),
      (RESOURCES_PATH + '/css/question_preview.css', tags.ResourcesHandler),
      (RESOURCES_PATH + '/css/student_progress.css', tags.ResourcesHandler),
      (RESOURCES_PATH + '/css/tipped.css', tags.ResourcesHandler),
    ]

    dashboard.DashboardHandler.add_sub_nav_mapping(
        'analytics', MODULE_NAME, MODULE_TITLE,
        action=AdminDashboardHandler.ADMIN_LIST_ACTION,
        href=AdminDashboardHandler.ADMIN_LIST_URL,
        placement=1000, sub_group_name='pinned')

    global custom_module  # pylint: disable=global-statement
    custom_module = custom_modules.Module(
        MODULE_TITLE,
        'A set of pages for managing course teachers.',
        global_routes, handlers,
        notify_module_enabled=notify_module_enabled)

    return custom_module
