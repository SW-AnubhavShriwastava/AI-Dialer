from typing import List, Optional


class CallContext:
    """Store context for the current call."""
    def __init__(self):
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.call_ended: bool = False
        self.user_context: List = []
        self.system_message: str = ""
        self.initial_message: str = ""
        self.start_time: Optional[str] = None
        self.end_time: Optional[str] = None
        self.final_status: Optional[str] = None
        
        # New state tracking fields
        self.appointment_scheduled: bool = False
        self.whatsapp_sent: bool = False
        self.appointment_date: Optional[str] = None
        self.appointment_time: Optional[str] = None
        self.user_name: Optional[str] = None
        self.user_phone: Optional[str] = None
        self.whatsapp_confirmed: bool = False
        self.conversation_ended: bool = False
        
