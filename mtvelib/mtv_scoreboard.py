import logging


class mtv_scoreboard_event(object):
    def __init__(self, name='none', interface, strict=True, event):
        self.name = name
        self.interfaces = interfaces
        self.event  = event
        self.strict = strict



class mtv_scoreboard(object):

    def expect (self, event_list=[]):
        atomic_event  = {
            'name'      : <optional>,
            'interface' : <optional>,
            'event'     : mtv_scoreboard_event
        }

        event_sequence = {
            'name'     : <optional>,
            'sequence' : [
                {
                    'interface': <name>,
                    'events' : [list of atomic_event]
                },
            ]
        }

        
        event_list = [
            {
                name             : <>,
                event_list|event : [{interface:<>, ]
        
                                    
