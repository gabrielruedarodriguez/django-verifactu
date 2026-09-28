from django.dispatch import Signal

# Sent after the transaction that created the record commits.
record_created = Signal()
# Sent once the AEAT answer is stored: for each answered record, then for the submission.
record_answered = Signal()
submission_finished = Signal()
# Sent when a record is issued after a chain problem (Orden HAC/1177/2024, art. 7.i and 7.j).
alarm_raised = Signal()
