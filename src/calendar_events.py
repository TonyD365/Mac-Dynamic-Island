"""The next event from the user's calendars, through EventKit.

Nothing is read until the user switches Calendar Events on and macOS has granted access.
"""
import time

try:
    import EventKit
except ImportError:                 # the framework bindings are not installed
    EventKit = None

from Foundation import NSDate

LOOK_AHEAD = 12 * 3600              # how far ahead to look for the next event
JUST_STARTED = 5 * 60               # an event that began this recently still counts as "next"
_AUTHORIZED = (3,)                  # EKAuthorizationStatusAuthorized / FullAccess


class Calendar:
    def __init__(self):
        self.store = EventKit.EKEventStore.alloc().init() if EventKit else None

    def available(self):
        return self.store is not None

    def authorized(self):
        return self.available() and EventKit.EKEventStore.authorizationStatusForEntityType_(0) in _AUTHORIZED

    def denied(self):
        """True once the user (or a policy) has said no; macOS will not ask again."""
        return self.available() and EventKit.EKEventStore.authorizationStatusForEntityType_(0) in (1, 2)

    def request_access(self, done=None):
        """Ask macOS for calendar access; the answer arrives later on some other thread."""
        if not self.available():
            return
        finished = lambda granted, error: done(bool(granted)) if done else None
        if hasattr(self.store, "requestFullAccessToEventsWithCompletion_"):     # macOS 14 and later
            self.store.requestFullAccessToEventsWithCompletion_(finished)
        else:
            self.store.requestAccessToEntityType_completion_(0, finished)

    def next_event(self, now=None):
        """{'id', 'title', 'start', 'end'} (times as seconds since 1970) of the next timed event, or None."""
        if not self.authorized():
            return None
        now = time.time() if now is None else now
        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            NSDate.dateWithTimeIntervalSince1970_(now - JUST_STARTED),
            NSDate.dateWithTimeIntervalSince1970_(now + LOOK_AHEAD), None)
        found = []
        for event in self.store.eventsMatchingPredicate_(predicate) or []:
            if event.isAllDay():
                continue
            found.append({"id": str(event.eventIdentifier()), "title": str(event.title() or "Event"),
                          "start": event.startDate().timeIntervalSince1970(),
                          "end": event.endDate().timeIntervalSince1970()})
        return pick_next(found, now)


def pick_next(events, now):
    """The soonest event that has not ended and did not start more than a few minutes ago."""
    current = [e for e in events if e["end"] > now and e["start"] > now - JUST_STARTED]
    return min(current, key=lambda e: e["start"]) if current else None


def describe(event, now, clock):
    """'10:30  ·  in 25 min' for the island's subtitle; `clock` formats a time of day."""
    minutes = (event["start"] - now) / 60.0
    if minutes <= 0:
        when = "now"
    elif minutes < 1:
        when = "in under a minute"
    elif minutes < 90:
        when = "in %d min" % round(minutes)
    else:
        when = "in %d h %02d min" % divmod(round(minutes), 60)
    return "%s  ·  %s" % (clock(event["start"]), when)
