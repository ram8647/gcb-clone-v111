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
import json
import random
import copy

from google.appengine.ext import db

from common import schema_fields
from common import utils as common_utils

#from controllers import utils

from models import entities
from models import models
#from models import resources_display
#from models import roles
#from models import transforms
#from models import event_transforms

#from models.models import QuestionDAO
#from models.models import QuestionGroupDAO
from models.models import MemcacheManager

GLOBAL_DEBUG = False

class StudentAnswersEntity(entities.BaseEntity):

    """A class that represents a persistent database entity for student answers."""
    recorded_on = db.DateTimeProperty(auto_now_add=True, indexed=True)
    user_id = db.StringProperty(indexed=True)
    email = db.StringProperty(indexed=True)
    answers_dict = db.TextProperty(indexed=False)   #json string

    memcache_key = 'studentanswers'

    @classmethod
    def record(cls, user, data):
        """Records a student tag-assessment into a datastore.

           A tag-assessment includes a student attempt at a quiz question.
           The user's email is used as the key for the StudentAnswersEntity.

           Initially an randomly generated numeric id was used as the key
           for StudentAnswersEntity.  That made it difficult to lookup
           student data from the datastore without having to perform a
           very expensive query. So, we switched to an email-based key, which
           lets us retrieve a single record from the db with a key.get().

           However, the datastore in ram8647 already had a couple of thousand records
           in it and we were unable to revise it.  So this code works with
           both the legacy and new formats.
           
           In mobilecsp-2017, we ran into a similar problem with emails with mixed case being used as keys and causing problems, so this algorithm was adapted to create new entities with lowercase keys.

           Algorithm:
              First try to get the Entity using the student's key.  If
              that succeeds then proceed with updating the answers_dict.
              If that fails, then try getting the Entity using a query
              on the student's email (expensive).  If that succeeds,
               create a new Entity as a copy of the existing one with
              the lowercase email as its key.  If that fails, then this is the occurrence for the student -- make a new Entity.
           There are about 35 mixed case StudentAnswerEntities that we should delete once new entities are made.
          
        """
        # Try to get the student's data by email key from datastore
        emailOrig = user.email()
        email = emailOrig.lower()  # convert to lowercase!
        key = db.Key.from_path('StudentAnswersEntity', email)
        if GLOBAL_DEBUG:
            logging.debug('***BAH*** email.lower() ' + email + ' key = ' + str(key) + ' emailOrig = ' + emailOrig)
        student = db.get(key)

        if student:
            #  If student (with email key) found
            if GLOBAL_DEBUG:
                logging.warning('***RAM*** existing student key =  ' + email)
            student.answers_dict = cls.update_answers_dict(student, data, user)
            student.recorded_on = datetime.datetime.now()
            student.put()
        else:
            # Try to query the db by email to get student
            student = cls.get_student_by_email(email, user)
            if student:
                if GLOBAL_DEBUG:
                    logging.warning('***BAH*** record: updating student by email instead of key ' + email)
                student.answers_dict = cls.update_answers_dict(student, data, user)
                student.recorded_on = datetime.datetime.now()
                student.put()
            else:
                # No student with that email in Db -- create a new Entity
                # Now using lowercase email! (BAH 8/12/17)
                if GLOBAL_DEBUG:
                    logging.warning('***RAM*** creating new ' + email)
                student = cls(key_name = email.lower())
                dict = cls.update_answers_dict(None, data, user)
                student.answers_dict = dict
                student.user_id = user.user_id()
                student.email = email
                student.put()

    @classmethod
    def get_student_by_email(cls, email, user):
        if GLOBAL_DEBUG:
            logging.warning('***RAM*** get by email ' + email)

        # Fetch the student by query on the email
        # If no hit, return None which will cause a new Entity
        student = cls.all().filter('email',email).get()
        if not student:
            if GLOBAL_DEBUG:
                logging.warning('***RAM***  no hit for email ' + email)
            return None
        else:
            # Old: Here were are converting the student's answers entity
            # from using an integer key to using the email as key.
            # THis will make retrievals way more efficient.
            # New: Converting to lowercase email key
            if GLOBAL_DEBUG:
                logging.warning('***BAH*** creating new entity with lowercase key ' + email)
            new_student = cls(key_name = email.lower())
            new_student.answers_dict = student.answers_dict
            new_student.user_id = student.user_id
            new_student.email = email
            return new_student

    @classmethod
    def update_answers_dict(cls, student, data, user):
        if student:    # Student dict already exists
            #logging.debug('***RAM*** data = ' + str(data))
            ## data_json = json.loads(data)
            dict = json.loads(student.answers_dict)
            dict = cls.build_dict(dict, data, user)
            return json.dumps(dict)
        else:
            dict = cls.build_dict(None, data, user)  # New student Dict
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** dict ' + str(dict))
            return json.dumps(dict)

    @classmethod
    def build_dict(cls, dict, data, user):
        """ Builds a dict for recording student performance on questions.

           The dict is indexed by student email and id and contains a complete
           record of the students scores and attempts for questions and Quizly
           exercises.

           POLICY: The score recorded is the last score recorded. So if a
           student gets a question correct and then redoes it and gets it wrong,
           the wrong answer and score of 0 is what would be recorded here.
           Should this be changed?
        """
#        data_json = json.loads(data)
        data_json = data
        url = data_json['location']
        unit_id =  str(url[url.find('unit=') + len('unit=') : url.find('&lesson=')])
        lesson_id = str(url[ url.find('&lesson=') + len('&lesson=') : ])
        instance_id = data_json['instanceid']
        if 'answer' in data_json:           # Takes care of SA_questions? that are missing answer?
             answers = data_json['answer']
        else:
             answers = [False]           # An array b/c of multi choice with multiple correct answers
        score = data_json['score']
        mytype = data_json['type']
        quid = None
        if 'quid' in data_json:          # Regular (not Quizly) question
            quid = data_json['quid']
        workspace = None
        if 'workspace' in data_json:     # Quizly workspace (student solution)
            workspace = data_json['workspace']
        if not dict:
            dict = {}
            dict['email'] = user.email().lower() # lowercase!
            dict['user_id'] = user.user_id()
            dict['answers'] = cls.build_answers_dict(None, unit_id, lesson_id, instance_id, quid, answers, score, mytype, workspace)
        else:
            answers_dict = dict['answers']
            dict['answers'] = cls.build_answers_dict(answers_dict, unit_id, lesson_id, instance_id, quid, answers, score, mytype, workspace)
        return dict

    @classmethod
    def build_answers_dict(cls, answers_dict, unit_id, lesson_id, instance_id, quid, answers, score, type, workspace):
        """ Builds the answers dict.

            Takes the form:
            answers = {unit_id: {lesson_id: {instance_id: {<answer data>}}}}

            The rest of the data -- e.g., sequence,choices -- has to be computed when the data
            are sent to the client.
        """

        timestamp = int((datetime.datetime.now() - datetime.datetime(1970, 1, 1)).total_seconds())
        attempt = {'question_id': quid, 'answers': answers, 'score': score,
                   'attempts': 1, 'question_type': type, 'timestamp': timestamp,
                   'workspace': workspace,
                   # Not sure whether the rest are needed
                   'weighted_score': 1, 'lesson_id': lesson_id, 'unit_id': unit_id, 'possible_points': 1,
                   'tallied': False, 'ever_completed': False
                 }
        if (score == 1):
            attempt['ever_completed'] = True

        if answers == 'true' or answers == 'false':   # Quizly answers, put into an array
            attempt['answers'] = [ answers ]
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** Quizly answers = ' + str(answers) + ' a= '  + str(attempt['answers']))

        # Create new answers_dict
        if not answers_dict:
            answers_dict = {}
            lesson = {instance_id: attempt }
            unit = {lesson_id: lesson }
            answers_dict = {unit_id: unit }
        # Update existing answers_dict
        else:
            if unit_id in answers_dict:
                if lesson_id in answers_dict[unit_id]:
                    if instance_id in answers_dict[unit_id][lesson_id]:
                        answers_dict[unit_id][lesson_id][instance_id]['attempts'] += 1
                        answers_dict[unit_id][lesson_id][instance_id]['answers'] = answers
                        answers_dict[unit_id][lesson_id][instance_id]['score'] = score
                        answers_dict[unit_id][lesson_id][instance_id]['workspace'] = workspace
                        if (score == 1):
                            answers_dict[unit_id][lesson_id][instance_id]['ever_completed'] = True
                    else:
                        answers_dict[unit_id][lesson_id][instance_id] = attempt
                else:
                    lesson = {instance_id: attempt}
                    answers_dict[unit_id][lesson_id] = lesson
            else:
                lesson = {instance_id: attempt}
                unit = {lesson_id: lesson}
                answers_dict[unit_id] = unit
        return answers_dict

    @classmethod
    def get_answers_dict_for_student(cls, student):
        """ Retrieve the answers dict for a student. """
        if (hasattr(student, 'is_transient')):
            if student.is_transient:
                return {}
  
        email = student.email
        if GLOBAL_DEBUG:
            logging.warning('***RAM*** get answers dict for student, email = ' + email)
        key = db.Key.from_path('StudentAnswersEntity', email)
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** email ' + email + ' key = ' + str(key))
        student_answers = db.get(key)
        dict = {}
        if student_answers:
            dict = json.loads(student_answers.answers_dict)
        else:
            # NEW (BAH, 8/12/17) to deal with the mixed case email keys
            # Try to query the db by email to get student (those are all lowercase now)
            student_answers = cls.get_student_by_email(email, student)
            if student_answers:
                 dict = json.loads(student_answers.answers_dict)
            if GLOBAL_DEBUG:
                logging.debug('***BAH*** getting student by email instead of key ' + email +  str(student_answers))
        return dict

    def put(self):
        """Do the normal put() and also invalidate memcache."""
        result = super(StudentAnswersEntity, self).put()
        MemcacheManager.delete(self.memcache_key)
        return result

    def delete(self):
        """Do the normal delete() and invalidate memcache."""
        super(StudentAnswersEntity, self).delete()
        MemcacheManager.delete(self.memcache_key)
