__author__ = 'ehiller@css.edu'
__author__ = 'ram8647@gmail.com'

import datetime
import logging
import random
import traceback

from models import transforms
from models.models import Student
from models.models import EventEntity
from models import utils as models_utils
from models import jobs
from models import event_transforms

from models.models import QuestionDAO
from models.models import QuestionGroupDAO
from models.models import MemcacheManager

from models.progress import UnitLessonCompletionTracker

GLOBAL_DEBUG = False

class ActivityScoreParser(jobs.MapReduceJob):
    """
        Class to parse the data returned from query of Event activities.

        An tag-assessment Event is recorded every time a student attempts
        a GCB question or Quizly exercise.  The only way to determine
        student performance on questions and exercises is to
        query the Events database, extract tag-assessment events and
        process them.
    """

    CUTOFF_DATE = datetime.datetime(2016,8,1)


    def __init__(self):
        """holds activity score info unit -> lesson -> question"""
        self.activity_scores = { }
        self.params = {}
        self.num_attempts_dict = { }
       
        # This is a table of all the Quizly exercises currently in the course.  It is used to provide a
        #  description in the Student Dashboard and also to validate that an instance_id is still 
        #  currently valid. 
        self.quizly_desc = {               # instance_id:description
            'LXgF4NO50hNM':{'desc':'Quizly, Pause the Player','name':'quiz_pause_the_player'},       # Unit 2
            'BtQ8hSoGkeml':{'desc':'Quizly, Stop the Player','name':'quiz_button_click_stop_player'},
            'Dstsv7VuDQb5':{'desc':'Quizly, Stop Player if playing','name':'quiz_stop_player_if_playing'},
            'twxBgieSEwqs':{'desc':'Quizly, If/else stop/start Player','name':'quiz_if_else_stop_start_player'},
            'a3uBZXYSOJee':{'desc':'Quizly, Set background color','name':'quiz_background_color'},   # Unit 3
            'pnhvzarYPPW1':{'desc':'Quizly, Set text color','name':'quiz_text_color'},
            'G3qzTftPYKTe':{'desc':'Quizly, Increment a variable','name':'quiz_incrementing'},
            '4kITN7u5hdsO':{'desc':'Quizly, Initialize global variable','name':'quiz_initialize_variable'},
            'pCZugPUxlHeb':{'desc':'Quizly, Initializing','name':'quiz_incrementing'},
            '8T30OkUf5r1r':{'desc':'Quizly, Simple if/else','name':'quiz_simple_if_else'},
            'KQctST8skmaC':{'desc':'Quizly, Procedure to double a variable','name':'quiz_proc_double'},
            'v2m4Ks25S1MX':{'desc':'Quizly, Procedure to add globals','name':'quiz_add_globals'},
            'rCgLbJRceEbn':{'desc':'Quizly, Procedure to reset the score','name':'quiz_reset_score'},     # Unit 4   
            '7uowepixSjT4':{'desc':'Quizly, Procedure to calculate the hit rate','name':'quiz_calculate_hit_rate'},
            'w18q4UWKxvlM':{'desc':'Quizly, Fix a bug in updateScore procedure','name':'quiz_procedure_bug'},
            'rvjUJMaLZ56s':{'desc':'Quizly, If/else greater than','name':'quiz_if_x_greater_than_y'},
            'scgF2VSCjUv8':{'desc':'Quizly, Simple if/else','name':'quiz_simple_if_else'},    # Unit 5
            'JatcV7u6GOer':{'desc':'Quizly, If x greater than y','name':'quiz_if_x_greater_than_y'},   
            #  No Quizly exercises beyond Unit 5 -->   we should create more!
        }

    @staticmethod
    def get_description():
        return 'activity answers parser'

    @staticmethod
    def entity_class():
        return EventEntity

    def get_num_attempts_dict():
        return _num_attempts_dict

    @classmethod
    def _get_questions_by_question_id(cls, questions_by_usage_id):
        ''' Retrieves every question in the course returning 
            them in a dict:  { id:questionDAO, ... }

            @param questions_by_usage_id.values() is a dict:
             {unit, lesson, sequence, weight, quid}
        '''
        ret = {}
        ret['single'] = {}
        ret['grouped'] = {}
        for question in questions_by_usage_id.values():
            question_single = QuestionDAO.load(question['id'])
            if question_single:
                ret['single'][question['id']] = question_single
            else:
                question_group = QuestionGroupDAO.load(question['id'])
                if question_group:
                    ret['grouped'][question['id']] = {}
                    for item in question_group.items:
                        ret['grouped'][question['id']][item['question']] = QuestionDAO.load(item['question'])
        return ret

    def build_additional_mapper_params(self, app_context):
        questions_by_usage_id = event_transforms.get_questions_by_usage_id(app_context)
        return {
            'questions_by_usage_id':
                questions_by_usage_id,
            'valid_question_ids': (
                event_transforms.get_valid_question_ids()),
            'group_to_questions': (
                event_transforms.get_group_to_questions()),
            'assessment_weights':
                event_transforms.get_assessment_weights(app_context),
            'unscored_lesson_ids':
                event_transforms.get_unscored_lesson_ids(app_context),
            'questions_by_question_id':
                ActivityScoreParser._get_questions_by_question_id(questions_by_usage_id)
            }

    def parse_quizly_scores(self, data, instance_id, timestamp, student, student_answers):
         """
             Processes Quizly exercises extracted from the Events query using the
             instance_id for the quid.

             Because Quizly exercises are not officially questions -- something that
             needs to be fixed -- they don't have a quid and need to be processed in
             an ad-hoc way. There is no question_info dict that can be used to get
             information about Quizly exercises.

             Also Quizly exercises don't have a 'sequence' number within the lesson.
             To get around that we assign random numbers starting at 10. One problem
             with this approach is that it doesn't preserve the sequence of Quizly
             exercises within the lesson.
         """

         # Check that the question is still a valid question (things move around)
         if not instance_id in self.quizly_desc:
             return

         if GLOBAL_DEBUG:
             logging.debug('***RAM*** A question with instance_id = ' + str(instance_id) +
              ' and no quid and location = ' + str(data['location']))
         url = data['location']
         quizly_unit_id =  int(url[url.find('unit=') + len('unit=') : url.find('&lesson=')])
         quizly_lesson_id = int(url[ url.find('&lesson=') + len('&lesson=') : ])
         quizly_score = data['score']

         if 'answer' in data:           # Takes care of legacy events that are missing answer?
             quizly_answer = data['answer']
         else:
             quizly_answer = False

         quizly_type = 'Quizly'      # reported in data as SaQuestion
         quizly_sequence = random.randint(10,30)                  #### Make up a random sequence #

         # Create a dict for this Quizly exercise
         question_answer_dict = {}
         question_answer_dict['unit_id'] = quizly_unit_id
         question_answer_dict['lesson_id'] = quizly_lesson_id
         question_answer_dict['sequence'] = quizly_sequence       # Not given
         question_answer_dict['question_id'] = instance_id        # Use instance_id as quid
         if instance_id in self.quizly_desc:
             question_answer_dict['description'] = self.quizly_desc[instance_id]
         else:
             question_answer_dict['description'] = 'Quizly ' + instance_id
         question_answer_dict['question_type'] = quizly_type
         question_answer_dict['timestamp'] = timestamp
         question_answer_dict['answers'] = [quizly_answer]   # T or F
         question_answer_dict['score'] = quizly_score
         question_answer_dict['weighted_score'] = quizly_score
         question_answer_dict['tallied'] = False
         question_answer_dict['choices'] = [{'text':'T','score':1},{'text':'F','score': 0}]   # Quizly's are T/F

         # Use the instance_id to count the number of attempts for each Quizly exercise by a given student
         if not student.email in self.num_attempts_dict:
             self.num_attempts_dict[student.email] = {}
         if not instance_id in self.num_attempts_dict[student.email]:
             self.num_attempts_dict[student.email][instance_id] = 1
         else:
             self.num_attempts_dict[student.email][instance_id] += 1

         # Either add the dict to the lesson_answers or update an existing one
         unit_answers = student_answers.get(quizly_unit_id, {})
         lesson_answers = unit_answers.get(quizly_lesson_id, {})

         found = False
         for seq in lesson_answers:
             if lesson_answers[seq]['question_id'] == instance_id:      # Quizly already there
                 found = True
                 if GLOBAL_DEBUG:
                     logging.debug('***RAM*** Quizly found answer for seq = ' + str(seq))
                 if lesson_answers[seq]['timestamp'] < timestamp:      # Already there check time
                     question_answer_dict['sequence'] = seq
                     lesson_answers[seq] = question_answer_dict        # Replace it
         if not found:
             lesson_answers[quizly_sequence] = question_answer_dict    # Add Quizly
             if GLOBAL_DEBUG:
                 logging.debug('***RAM*** Q ' + str(quizly_unit_id) + ' ' + str(quizly_lesson_id) + ' answers after ' + str(lesson_answers))

         #  Add the Quizly exercise into the student's activity_scores
         unit_answers[quizly_lesson_id] = lesson_answers
         student_answers[quizly_unit_id] = unit_answers
         self.activity_scores[student.email] = student_answers

    def parse_question_scores(self, instance_id, questions, student_answers, answers, student, timestamp):
        """
           Processes question scores within a given lesson.

           Questions within each lesson contain a quid (question_id) and a sequence
           number.
        """
        question_info = questions[instance_id]
        unit_answers = student_answers.get(question_info['unit'], {})
        lesson_answers = unit_answers.get(question_info['lesson'], {})

        question_desc = None   # Get's filled in later


        # answers is the unpacked answers from the Event query
        for answer in answers:
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** answer.question.id = ' + str(answer.question_id) + ' type= ' + str(answer.question_type) + ' s= ' + student.email)

        # Count the number of attempts for each answer by the student
            if not student.email in self.num_attempts_dict:
                self.num_attempts_dict[student.email] = {}

            if not answer.question_id in self.num_attempts_dict[student.email]:
                self.num_attempts_dict[student.email][answer.question_id] = 1
            else:
                self.num_attempts_dict[student.email][answer.question_id] += 1

            # Create a dict for this answer
            question_answer_dict = {}
            question_answer_dict['unit_id'] = answer.unit_id
            question_answer_dict['lesson_id'] = answer.lesson_id
            question_answer_dict['sequence'] = answer.sequence
            question_answer_dict['question_id'] = answer.question_id
            question_answer_dict['question_desc'] = question_desc
            question_answer_dict['question_type'] = answer.question_type
            question_answer_dict['timestamp'] = answer.timestamp
            question_answer_dict['answers'] = answer.answers
            question_answer_dict['score'] = answer.score
            question_answer_dict['weighted_score'] = answer.weighted_score
            question_answer_dict['tallied'] = answer.tallied

            if GLOBAL_DEBUG:
                logging.debug('***RAM*** Q ' + str(answer.unit_id) + ' ' + str(answer.lesson_id) + ' unit answer before ' + str(unit_answers))
                logging.debug('***RAM*** McQ ' + str(answer.unit_id) + ' ' + str(answer.lesson_id) + ' answers before ' + str(lesson_answers))

            # If the timestamp on this event is after the timestamp on a previous score do an update
            if answer.sequence in lesson_answers and lesson_answers[answer.sequence]['timestamp'] < timestamp:
                if GLOBAL_DEBUG:
                    logging.debug('***RAM*** lesson answers timestamp ' + str(lesson_answers[answer.sequence]) + ' < ' + str(timestamp))
                lesson_answers[answer.sequence] = question_answer_dict
            elif answer.sequence not in lesson_answers:
                lesson_answers[answer.sequence] = question_answer_dict
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** McQ ' + str(answer.unit_id) + ' ' + str(answer.lesson_id) + ' answers after ' + str(lesson_answers))

        #  Add scores for this question into the student's activity_scores
        unit_answers[question_info['lesson']] = lesson_answers
        student_answers[question_info['unit']] = unit_answers
        self.activity_scores[student.email] = student_answers

    def parse_activity_scores(self, activity_attempt):
        '''
           Processes activity scores recieved from the mapper.

           This is called in the mapper callback function.  Each time a student attempts
           a GCB question or a Quizly exercise, a tag-assessment Event is created.
           This processes such events to extract the number of attempts the student
           made and the answers.

           Events are time-stamped and recorded by user_id. They include the instance_id
           of the Component that triggered the Event.  Both GCB questions and Quizly
           exercises have an instance_id.

           However, Quizly exercises don't have question_id and need special processing.

           Use the Dashboard to see what the data looks like for Events:
           https://console.cloud.google.com/datastore/entities/query?
               project=ram8647&ns=ns_mobileCSP&kind=EventEntity
        '''

        if activity_attempt.source == 'tag-assessment':
            data = transforms.loads(activity_attempt.data)
            instance_id = data['instanceid']
            if GLOBAL_DEBUG:
                logging.debug('***********RAM************** data[instanceid] = ' + instance_id)
            timestamp = int(
                (activity_attempt.recorded_on - datetime.datetime(1970, 1, 1)).total_seconds())

            # Get information about the course's questions (doesn't include Quizly exercises yet)
            questions = self.params['questions_by_usage_id']
            valid_question_ids = self.params['valid_question_ids']
            assessment_weights = self.params['assessment_weights']
            group_to_questions = self.params['group_to_questions']

            student = Student.get_by_user_id(activity_attempt.user_id)

            #  Get this student's answers so far
            student_answers = self.activity_scores.get(student.email, {})
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** student answers = ' + str(student_answers))

            answers = event_transforms.unpack_check_answers(            # No Quizly answers in here
                data, questions, valid_question_ids, assessment_weights,
                group_to_questions, timestamp)

            # Add the score to right lesson
            # NOTE: This was throwing an exception on Quizly exercises.  Shouldn't happen now
            try: 
                #  If the event is tag-assessment and has no quid, it's a Quizly exercise
                if not 'quid' in data:
                    self.parse_quizly_scores(data, instance_id, timestamp, student, student_answers)
                else:
                    self.parse_question_scores(instance_id, questions, student_answers, answers, student, timestamp)
            except Exception as e:
                logging.error('***********RAM************** bad instance_id: %s %s\n%s', str(instance_id), e, traceback.format_exc())
        if GLOBAL_DEBUG:       
            logging.debug('***RAM*** activity_scores ' + str(self.activity_scores))
        return self.activity_scores

    def build_missing_score(self, question, question_info, student_id, unit_id, lesson_id, sequence=-1):
        ''' Builds a partial question_answer_dict

            This is called for each student immediately after launching the mapper query.
        '''

        if sequence == -1:
            sequence = question['sequence']

        question_answer = None

        # If (unit,lesson) already in this student's activity_scores then
        #  question_answer is the next question_answer that matches the sequence.
        if unit_id in self.activity_scores[student_id] and lesson_id in \
                self.activity_scores[student_id][unit_id]:
            question_answer = next((x for x in self.activity_scores[student_id][unit_id][lesson_id].values()
                                    if x['sequence'] == sequence), None)

        question_desc = None
        if question_info:
            question_desc = question_info.dict['description']

        possible_score = 0
        choices = None
        choices_scores_only = []
        if question_info:
            if 'choices' in question_info.dict:
                choices = question_info.dict['choices']

                if GLOBAL_DEBUG:
                    logging.debug('***RAM*** choices = ' + str(choices))

                # Calculate total possible points for questions by iterating
                # through the answer choices and summing their individual values.
                # For multiple choice questions, one choice will be 1.0 (correct)
                # and the others 0.0.  For multiple answer questions, each correct
                # is worth 1/n of the value, where n is the number of correct choices.
                # In any case, the total should typically sum to 1.0.
                # Q: Is possible score always 1?  If so why do we need this?
                i = 0
                for choice in choices:
                    if float(choice['score']) > 0:
                        possible_score += float(choice['score'])

                    # Calculating an abbreviated choices array that is passed back.
                    # We don't need the questions and answers text.
                    choices_scores_only.append( {'score': choice['score'], 'text': chr(ord('A') + i) } )
                    i = i + 1
                if GLOBAL_DEBUG:
                    logging.debug('***RAM*** scores only = ' + str(choices_scores_only))

            elif 'graders' in question_info.dict:
                choices = question_info.dict['graders']
                for grader in choices:
                    possible_score += float(grader['score'])
            if 'weight' in question and float(question['weight']) is not 0.0:
                possible_score = possible_score * float(question['weight'])
        else:
            possible_score = 1

        #  If there is no question_answer yet in activity_scores for this student
        #   construct a partial question_answer_dict with default values.  Otherwise
        #   fill in the existing dict with values from the student's question_answer.
        if not question_answer:
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** Initializing dict for ' +
                     str(unit_id) + ' ' + str(lesson_id) + ' ' + str(sequence))
            question_answer_dict = {}
            question_answer_dict['unit_id'] = unit_id
            question_answer_dict['lesson_id'] = lesson_id
            question_answer_dict['sequence'] = sequence
            question_answer_dict['question_id'] = question['id']
            question_answer_dict['description'] = question_desc
            question_answer_dict['question_type'] = 'NotCompleted'
            question_answer_dict['timestamp'] = 0
            question_answer_dict['answers'] = ''
            question_answer_dict['score'] = 0
            question_answer_dict['weighted_score'] = 0
            question_answer_dict['tallied'] = False
            question_answer_dict['possible_points'] = possible_score
            question_answer_dict['choices'] = choices_scores_only
#            question_answer_dict['choices'] = choices

            unit = self.activity_scores[student_id].get(unit_id, {})
            lesson = unit.get(lesson_id, {})
            lesson[sequence] = question_answer_dict
        else:
            if GLOBAL_DEBUG:
                logging.debug('***RAM*** Updating dict for ' +
                    str(question_answer['unit_id']) + ' ' + str(question_answer['lesson_id']) + ' ' + str(question_answer['sequence']) 
                    + ' score=' + str(question_answer['score']))
            question_answer_dict = {}
            question_answer_dict['unit_id'] = question_answer['unit_id']
            question_answer_dict['lesson_id'] = question_answer['lesson_id']
            question_answer_dict['sequence'] = question_answer['sequence']
            question_answer_dict['question_id'] = question_answer['question_id']
            question_answer_dict['description'] = question_desc
            question_answer_dict['question_type'] = question_answer['question_type']
            question_answer_dict['timestamp'] = question_answer['timestamp']
            question_answer_dict['answers'] = question_answer['answers']
            question_answer_dict['score'] = question_answer['score']
            question_answer_dict['weighted_score'] = question_answer['weighted_score']
            question_answer_dict['tallied'] = question_answer['tallied']
            question_answer_dict['possible_points'] = possible_score
            question_answer_dict['choices'] = choices_scores_only
#            question_answer_dict['choices'] = choices

            self.activity_scores[student_id][unit_id][lesson_id][sequence] = question_answer_dict

    #validate total points for lessons, need both question collections for score and weight
    def build_missing_scores(self):
        ''' This is called from get_activity_scores right after launching the query mapper.

            For each student in activity_scores, it sets up a data dict with partial
            score data that is filled in when the scores are retrieved.
        '''
        questions = self.params['questions_by_usage_id']
        questions_info = self.params['questions_by_question_id']
        for student_id in self.activity_scores:
            for question in questions.values():
                unit_id = question['unit']
                lesson_id = question['lesson']

                question_info = questions_info['single'].get(question['id'], None) #next((x for x in questions_info if x
                #  and
                # x.id == question['id']), None)
                if not question_info:
                    question_info_group = questions_info['grouped'][question['id']]
                    sequence = question['sequence']
                    for question_info in question_info_group.values():
                        self.build_missing_score(question, question_info, student_id, unit_id, lesson_id, sequence)
                        sequence += 1
                else:
                    self.build_missing_score(question, question_info, student_id, unit_id, lesson_id)

    @classmethod
    def get_student_completion_data(cls, course):
        """Retrieves student completion data for the course."""

        if GLOBAL_DEBUG:
            logging.debug('***RAM*** get_student_completion_data ' + str(course))
        completion_tracker = UnitLessonCompletionTracker(course)
        questions_dict = completion_tracker.get_id_to_questions_dict()
#         for q in questions_dict:
#             logging.debug('***RAM*** key: ' + q)
#             logging.debug('***RAM*** dict ' + str(questions_dict[q]))

    @classmethod
    def get_activity_scores(cls, student_user_ids, course, force_refresh = True):
        """Retrieve activity data for student using EventEntity.

           For each student, launch a Query of EventEntities to retrieve student
           scores.  The Query is launched as a map-reduce background process that
           will return up to 500 results, reporting back every second.  It reports
           back by calling the map_fn callback, which in turn calls parse_activity
           scores.

           As soon as the Query is launched (in the background) the foreground
           process calls build_missing_scores() to construct a student_answer.dict
           that will be updated as score data for that student is received.

           Events properties include a userid (a number) and a source (e.g.,
           tag-assessement), a  recorded-on date (timestamp) and data (a dictionary).
           Here's a typeical data dict:

           {"loc": {"city": "mililani", "language": "en-US,en;q=0.8", "locale": "en_US",
           "country": "US", "region": "hi", "long": -158.01528099999999, "lat": 21.451331,
           "page_locale": "en_US"}, "instanceid": "yOkVTqWogdaF", "quid": "5733935958982656",
           "score": 1, "location": "https://mobilecsp-201608.appspot.com/mobilecsp/unit?unit=1&lesson=45",
           "answer": [0, 1, 2, 4], "type": "McQuestion", "user_agent":
            "Mozilla/5.0 ..."}

           Note that it includes the unit_id and lesson_id as part of the Url
        """

        # Instantiate parser object
        cached_date = datetime.datetime.now()
        activityParser = ActivityScoreParser()

        if force_refresh:
            activityParser.params = activityParser.build_additional_mapper_params(course.app_context)

            #  Launch a background Query for each student's activity data.  This is expensive.
            for user_id in student_user_ids:
#                if GLOBAL_DEBUG:
                logging.debug('***RAM*** launching a query for student ' + str(user_id))
                mapper = models_utils.QueryMapper(
                    EventEntity.all().filter('user_id in', [user_id])       \
                                     .filter('recorded_on  >= ', cls.CUTOFF_DATE), \
                                        batch_size=1000, report_every=1000)

                # Callback function -- e.g., 45-50 callbacks per query
                def map_fn(activity_attempt):
#                    if GLOBAL_DEBUG:
#                     logging.debug('***RAM*** map_fn ' + str(activity_attempt))
                    activityParser.parse_activity_scores(activity_attempt)

                mapper.run(map_fn)

            #  In the foreground create the student_answer_dict, which is stored at:
            #   activity_scores[student][unit][lesson][sequence]  where sequence is
            #   the question's sequential position within the lesson.
            #  So each question in the lesson will have a question_answer_dict.
            activityParser.build_missing_scores()

            #Lets cache results for each student
            for user_id in student_user_ids:
                cached_student_data = {}
                cached_student_data['date'] = cached_date

                student = Student.get_by_user_id(user_id)
                
                cached_student_data['scores'] = activityParser.activity_scores.get(student.email, {})
                cached_student_data['attempts'] = activityParser.num_attempts_dict.get(student.email, {})
                MemcacheManager.set(cls._memcache_key_for_student(student.email),cached_student_data)
        else:
            uncached_students = []
            for student_id in student_user_ids:
                if student_id != '':
                    student = Student.get_by_user_id(student_id)
                    temp_email = student.email
                    temp_mem = cls._memcache_key_for_student(temp_email)
                    scores_for_student = MemcacheManager.get(temp_mem)
                    if scores_for_student:
                        cached_date = scores_for_student['date']
                        activityParser.activity_scores[student_id] = scores_for_student['scores']
                        activityParser.num_attempts_dict[student_id] = scores_for_student['scores']
                    else:
                        uncached_students.append(student_id)
            if len(uncached_students) > 0:
                if cached_date == None or datetime.datetime.now() < cached_date:
                    cached_date = datetime.datetime.now()

                activityParser.params = activityParser.build_additional_mapper_params(course.app_context)

                for user_id in uncached_students:
                    mapper = models_utils.QueryMapper(
                        EventEntity.all().filter('user_id in', [user_id])       \
                                     .filter('recorded_on  >= ', cls.CUTOFF_DATE), \
                                        batch_size=1000, report_every=1000)

                    def map_fn(activity_attempt):
                        activityParser.parse_activity_scores(activity_attempt)

                    mapper.run(map_fn)

                activityParser.build_missing_scores()

                #Lets cache results for each student
                for user_id in uncached_students:
                    cached_student_data = {}
                    cached_student_data['date'] = cached_date

                    student = Student.get_by_user_id(user_id)

                    cached_student_data['scores'] = activityParser.activity_scores.get(student.email, {})
                    MemcacheManager.set(cls._memcache_key_for_student(student.email),cached_student_data)

        score_data = {}
        score_data['date'] = cached_date
        score_data['scores'] = activityParser.activity_scores
        score_data['attempts'] = activityParser.num_attempts_dict
        if GLOBAL_DEBUG:
            logging.debug('***RAM*** get_activity_scores returning scores: ' + str(score_data['scores']))

        return score_data

    @classmethod
    def _memcache_key_for_student(cls, user_id):
        return ('activityscores:%s' % user_id)
