#
#    Quizly Exercises for Course Builder
#
#    Copy Right (C) 2013 Ralph Morelli (ram8647@gmail.com)
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this library; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
#    USA
#

"""Quizly exercises for Course Builder.


This extension lets you host Quizly exercises in your Course Builder
course. These exercises provide live-coding App Inventor exercises.

Here is how to install, activate and use this module:
    - download Course Builder
    - download this package
    - copy all files in this package into /modules/quizly/... folder of your
      Course Builder application folder
    - edit main.py of your application
        - add new import where all other modules are imported:
          import modules.quizly.quizly
        - enable the module, where all other modules are enabled:
          modules.quizly.quizly.register_module().enable()
    - restart your local development sever or re-deploy your application
    - TODO:  In GCB 1.10, Quizly Exercise doesn't show up in component editor

     -------- The following points no longer apply
    - edit a lesson using visual editor; you should be able to add a new
      component type "Ram8647: Quizly Exercise"
    - the component editor should show a list of all available Quizly exercises in a
      dropdown list; these are from the file: assets/lib/quizly/quizzes.json 
    - pick one exercise, save the component configuration
    - add empty exercise definition var activity = []; uncheck 'Activity Listed'
    - save  the lesson
    - enable gcb_can_persist_activity_events and gcb_can_persist_page_events
    - preview the lesson
    - click "Check Answer" and see how data is recorded in the datastore
      EventEntity table with a namespace appropriate for your course
    - this is it!

This work is based on Simikov's khanex project, which brings Khan Academy exercises to
WordPress. You can learn more about it here:
  http://www.softwaresecretweapons.com/jspwiki/khan-exercises
"""

__author__ = 'Pavel Simakov (pavel@vokamis.com), Ralph Morelli (ram8647@gmail.com)'

import json
import logging
import cgi
import os
import urllib2
import urlparse
import urllib
from xml.etree import cElementTree
import zipfile

from common import schema_fields
from common import tags
from controllers import sites
from controllers import utils
from models.config import ConfigProperty
from models.counters import PerfCounter
from models import custom_modules
from models import models
from models import transforms
from google.appengine.api import users

# Add 'quizly' to TRACKABLE_COMPONENTS to keep track of progress on Quizly quizzes
from models.progress import TRACKABLE_COMPONENTS 
TRACKABLE_COMPONENTS.append('quizly')

ATTEMPT_COUNT = PerfCounter(
    'gcb-quizly-attempt-count',
    'A number of attempts made by all users on all exercises.')

WHITELISTED_EXERCISES = ConfigProperty(
    '_quizly_whitelisted', str, (
        'White-listed exercises that can be shown to students. If this list '
        'is empty, all exercises are available.'),
    default_value='', multiline=True)

def _allowed(name):
    """Checks if an exercise name is whitelisted for use."""
    return (
        not WHITELISTED_EXERCISES.value or
        name in WHITELISTED_EXERCISES.value)

class QuizlyExerciseTag(tags.BaseTag):
    """Custom tag for embedding Quizly Exercises."""

    @classmethod
    def name(cls):
        return 'Quizly Exercise'

    @classmethod
    def vendor(cls):
        return 'ram8647'

    def render(self, node, handler):

        #  Get the context and the Quizly question data
        student = handler.student
        unitid = handler.unit_id
        lessonid = handler.lesson_id

        quizname = node.attrib.get('quizname')
        instanceid = node.attrib.get('instanceid')
        preamble = node.attrib.get('preamble')
        preamble = urllib2.quote(preamble)

        id_iconholder = 'icon-holder-' + quizname    #  Div where icon goes in HTML doc

        if not student.is_transient:
            logging.info('RAM: *** QUIZLY render: student=%s unit=%s lesson=%s instance=%s quiz=%s', student.email,unitid, lessonid, instanceid, quizname)

        # Creates a record of quiz on window.quizlies.
        script = ''
        script += '<script>'
        script += 'if (!window.quizlies) {window.quizlies={};}'
        script += 'var quiz = {};'
        script += 'quiz.name="' + quizname + '";'
        script += 'quiz.id="' + instanceid + '";'
        script += 'window.quizlies["' + quizname + '"]= quiz;'
#        script += 'console.log("instanceid="' + instanceid + '"");'  # syntax error here
        script += '</script>'

        # View attributes        
        height = node.attrib.get('height') or '595'
        width = node.attrib.get('width') or '755'
        hasanswerbox = node.attrib.get('hasanswerbox') or 'false'
        isrepeatable = node.attrib.get('isrepeatable') or 'false'
        hashints = node.attrib.get('hints') or 'true'

        #  Source of the iframe that will be loaded for this quiz
        src = 'assets/lib/quizly/gcb-index.html?backpack=hidden&selector=hidden&quizname=' + quizname
        if preamble:
          src += '&heading=' + preamble
        src += '&hints=' + hashints
        src += '&repeatable=' + isrepeatable

        # Has this question already been completed, in-progress, or not-started?
        progress_tracker = handler.get_course().get_progress_tracker()
        status = 0
        if not student.is_transient:
            student_progress = progress_tracker.get_or_create_progress(student)
            status = progress_tracker.get_component_status(unitid, lessonid,instanceid,student)

        # Handler for the checkAnswer button. Quizly puts the quizName and result
        #  on window.parent.quizlies and this script reads it from there.

        # NOTE:  gcbAudit() is in activity-generic.js.  For this to work, 'quizly' has to be
        #  added to TRACKABLE_COMPONENTS in models/progress.py

        script += '<script>function updateQuizlyProgressIcon(id, score) { '
        script += '  var qname = window.quizlies.quizname;'
        script += '  var iframes = document.getElementsByTagName(\'iframe\');'
        script += '  var iconholder = \'\';'
        script += '  var innerHtml = \'\';'
        script += '  if (score >= 1) '
        script += '    innerHtml = \'<img alt="Completed" class="gcb-progress-icon" src="assets/img/completed.png" title="Completed">\';'
        script += '  else'
        script += '    innerHtml = \'<img alt="In_progress" class="gcb-progress-icon" src="assets/img/in_progress.png" title="In progress">\';'
        script += '  for (var i=0; i < iframes.length; i++) { '
        script += '    var iframe = iframes[i];'
        script += '    if (iframe.src.indexOf(qname) != -1) { '
        script += '      iconholder = iframe.previousSibling.previousSibling;'        
        script += '      break;'
        script += '    }'
        script += '  }'
        script += '  if (iconholder != \'\') '
        script += '    iconholder.innerHTML = innerHtml;'
        script += '}'
        script += '</script>'

        script += '<script> function checkAnswer(){ '
        script +=   'var quizName = window.quizlies["quizname"];'
        script +=   'var instanceid = window.quizlies[quizName].id;'
        script +=   'var result = window.quizlies[quizName].result;'
        script +=   'var workspace = window.quizlies[quizName].workspace;'
        script +=   'var score = (result) ? 1 : 0;'
        script +=   'console.log("RAM (quizly.py):  That solution was " + result);'
        script +=   'if (gcbCanRecordStudentEvents) {'
        script +=      'console.log("RAM (quizly.py): POSTing to server");'
        script +=      'console.log("RAM (quizly.py): instanceid=" + instanceid);'
        script +=      'var auditDict = {'
        script +=         '\'instanceid\': instanceid,'
        script +=         '\'answer\': result,'
        script +=         '\'score\': score,'
        script +=         '\'type\': "SaQuestion",'
        script +=         '\'workspace\': workspace,'
        script +=      '};'
        script +=      'gcbAudit(gcbCanRecordStudentEvents, auditDict, "tag-assessment", true);'
        script +=   '}'
        script += '  updateQuizlyProgressIcon(instanceid, score);'
        script += '}'
        script += '</script>';

        returnStr = ''
        returnStr += script

        #  Add the box-surrounded iframe that will hold the quiz. Blockly will be a frame w/in this frame.
        returnStr += '<div style="border: 1px solid black; margin: 5px; padding: 5px;">'
        returnStr += '<div id="' + id_iconholder + '" class="gcb-progress-icon-holder gcb-pull-right">'
        pointsdiv = '<div class="qt-points"><em>1 point&nbsp;&nbsp;</em></div>'
#        returnStr += pointsdiv
        progress_img = ''
        if status == 0:
            progress_img += '<img src="assets/img/not_started.png" />'
        elif status == 1:
            progress_img += '<img src="assets/img/in_progress.png" />'
        else:
            progress_img += '<img src="assets/img/completed.png" />'
        returnStr += progress_img
        returnStr += '</div>'
        returnStr += pointsdiv
        returnStr += '<iframe style= "border: 0px; margin: 1px; padding: 1px;" src=' + src + ' width="' + width + '" height="' + height + '">'
        returnStr += '</iframe>'
        returnStr += '</div>'

        return tags.html_string_to_element_tree(returnStr)

    def get_icon_url(self):
        return '/mobilecsp/assets/img/quizly-gcb-edit-icon.png'

    def get_schema(self, unused_handler):
        """Construct a list of quiz names and desciptions"""
        items = []
        quizfile = open('assets/lib/quizly/quizzes.json')
        quizzes = json.load(quizfile)
        quizfile.close()
        for q in quizzes:
            items.append((q,'%s: %s' % (q, quizzes[q]['Description'])))

        reg = schema_fields.FieldRegistry(QuizlyExerciseTag.name())
        reg.add_property(
            schema_fields.SchemaField(
                'quizname', 'Exercises', 'select', optional=True,
                select_data=items,
                description=('The name of the Quizly exercise')))
        reg.add_property(
            schema_fields.SchemaField(
                'preamble', 'Preamble', 'string',
                optional=True,
                description='Introductory blurb for the quiz'))
        reg.add_property(
            schema_fields.SchemaField(
                'hasanswerbox', 'Answer Box', 'boolean',
                optional=True,
                extra_schema_dict_values={'value': 'false'},
                description='Input Text Field'))
#         reg.add_property(
#             schema_fields.SchemaField(
#                 'isrepeatable', 'New Question Button', 'boolean',
#                 optional=True,
#                 extra_schema_dict_values={'value': 'false'},
#                 description='New Question Button'))
        reg.add_property(
            schema_fields.SchemaField(
                'hints', 'Hints Button', 'boolean',
                optional=True,
                extra_schema_dict_values={'value': 'true'},
                description='Hints Button'))
        reg.add_property(
            schema_fields.SchemaField(
                'height', 'Height', 'string',
                optional=True,
                extra_schema_dict_values={'value': ''},
                description=('Height of the iframe')))
        reg.add_property(
            schema_fields.SchemaField(
                'width', 'Width', 'string',
                optional=True,
                extra_schema_dict_values={'value': '100%'},
                description=('Width of the iframe')))
        return reg

custom_module = None

def register_module():
    """Registers this module in the registry."""

    # register custom tag
    tags.Registry.add_tag_binding('quizly', QuizlyExerciseTag)

    # register module
    global custom_module
    custom_module = custom_modules.Module(
        'Quizly Exercise',
        'A set of exercises for delivering Quizly Exercises via '
        'Course Builder.',
        [], [])
    return custom_module
