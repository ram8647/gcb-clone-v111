    /**
     * Sets up handlers for the modal window that displays the quiz questions.
     *
     * How this works: Quiz previews are displayed using the GCB dashboard module.  
     * They use the template:  modules/dashboard/templates/question_preview.html and
     *  and require the style sheet:  assets/lib/lessons/question_preview.css.
     *  They script in question_preview requires that the iframe containing the
     *  preview be contained in a window named modal-window.  See the HTML code
     *  at the very bottom of this file.
     */
    var ESC_KEY = 27;

    function setUpModalWindow() {
      console.log('Setting up  modal');
      // Bind click on background and on close button to close window
      $("#question-background, #modal-window .gcb-button").on("click", function(e) {
	closeModal();
      });
      $("#question-container > div").hide();
    }

    function openModal() {
      // Bind Esc press to close window
      document.getElementById("student-detail-section").style.opacity = "0.25";
      $(document).on("keyup.modal", function(e) {
	  //	if (e.keyCode == ESC_KEY) {
	    closeModal();
	    //	}
      });
      $("#modal-window").show();
      document.getElementById('question-close-button').style.visibility='visible';
    }

    function closeModal() {
      $("#modal-window, #question-container > div").hide();
      //Remove Esc binding
      console.log('Closing modal');
      document.getElementById("student-detail-section").style.opacity = "1";
      $(document).off("keyup.modal");
    }
