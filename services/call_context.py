from typing import List, Optional, Dict
from datetime import datetime


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
        
        # Appointment tracking
        self.appointment_scheduled: bool = False
        self.whatsapp_sent: bool = False
        self.appointment_date: Optional[str] = None
        self.appointment_time: Optional[str] = None
        self.user_name: Optional[str] = None
        self.user_phone: Optional[str] = None
        self.whatsapp_confirmed: bool = False
        self.date_time_confirmed: bool = False
        self.property_of_interest: Optional[str] = None
        
        # Conversation state
        self.conversation_ended: bool = False
        self.asked_anything_else: bool = False
        self.last_response_was_no: bool = False
        

    def update_appointment_details(self, details: Dict[str, str]) -> bool:
        """Update appointment details and validate them."""
        try:
            if 'date' in details:
                # Validate date format
                date = datetime.strptime(details['date'], '%Y-%m-%d')
                self.appointment_date = date.strftime('%Y-%m-%d')
            
            if 'time' in details:
                # Validate time format
                time = datetime.strptime(details['time'], '%H:%M')
                self.appointment_time = time.strftime('%H:%M')
            
            if 'property' in details:
                self.property_of_interest = details['property']
            
            if 'name' in details:
                self.user_name = details['name']
            
            if 'phone' in details:
                self.user_phone = details['phone']
            
            # Update confirmation states
            if self.appointment_date and self.appointment_time:
                self.date_time_confirmed = True
                
            if all([self.appointment_date, self.appointment_time, self.user_name]):
                self.appointment_scheduled = True
                
            return True
        except ValueError as e:
            return False

    def can_send_whatsapp(self) -> tuple[bool, str]:
        """Check if all required details for WhatsApp are present."""
        if not self.whatsapp_confirmed:
            return False, "WhatsApp number not confirmed"
        
        if not self.date_time_confirmed:
            return False, "Appointment date and time not confirmed"
            
        if not self.user_name:
            return False, "User name not available"
            
        if not self.appointment_date:
            return False, "Appointment date not set"
            
        if not self.appointment_time:
            return False, "Appointment time not set"
            
        return True, "All details present"

    def reset_conversation_state(self):
        """Reset conversation state flags."""
        self.asked_anything_else = False
        self.last_response_was_no = False

    def mark_conversation_end(self):
        """Mark the conversation as ended and update final status."""
        self.conversation_ended = True
        self.call_ended = True
        self.end_time = datetime.now().isoformat()
        
