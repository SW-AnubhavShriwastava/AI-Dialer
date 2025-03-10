import importlib
import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List
from datetime import datetime

import google.generativeai as genai

from functions.function_manifest import tools
from logger_config import get_logger
from services.call_context import CallContext
from services.event_emmiter import EventEmitter
import asyncio
from functions.send_whatsapp import send_whatsapp

logger = get_logger("LLMService")

class AbstractLLMService(EventEmitter, ABC):
    def __init__(self, context: CallContext):
        super().__init__()
        self.system_message = context.system_message
        self.initial_message = context.initial_message
        self.context = context
        self.user_context = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": self.initial_message}
        ]
        self.partial_response_index = 0
        self.available_functions = {
            "transfer_call": self.transfer_call,
            "end_call": self.end_call,
            "send_whatsapp": send_whatsapp
        }
        self.sentence_buffer = ""
        context.user_context = self.user_context

    def set_call_context(self, context: CallContext):
        self.context = context
        self.user_context = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": context.initial_message}
        ]
        context.user_context = self.user_context
        self.system_message = context.system_message
        self.initial_message = context.initial_message

    @abstractmethod
    async def completion(self, text: str, interaction_count: int, role: str = 'user', name: str = 'user'):
        pass

    def reset(self):
        self.partial_response_index = 0

    def validate_function_args(self, args):
        try:
            return json.loads(args) if args else {}
        except json.JSONDecodeError:
            logger.info('Warning: Invalid function arguments returned by LLM:', args)
            return {}

    def split_into_sentences(self, text):
        sentences = re.split(r'([.!?])', text)
        sentences = [''.join(sentences[i:i+2]) for i in range(0, len(sentences), 2)]
        return sentences

    async def emit_complete_sentences(self, text, interaction_count):
        self.sentence_buffer += text
        sentences = self.split_into_sentences(self.sentence_buffer)
        
        for sentence in sentences[:-1]:
            await self.emit('llmreply', {
                "partialResponseIndex": self.partial_response_index,
                "partialResponse": sentence.strip()
            }, interaction_count)
            self.partial_response_index += 1
        
        self.sentence_buffer = sentences[-1] if sentences else ""

    # Tool function implementations
    async def transfer_call(self, context, args):
        from twilio.rest import Client
        account_sid = os.environ['TWILIO_ACCOUNT_SID']
        auth_token = os.environ['TWILIO_AUTH_TOKEN']
        transfer_number = os.environ['TRANSFER_NUMBER']
        client = Client(account_sid, auth_token)
        call_sid = context.call_sid

        await asyncio.sleep(8)
        try:
            call = client.calls(call_sid).fetch()
            call = client.calls(call_sid).update(
                url=f'http://twimlets.com/forward?PhoneNumber={transfer_number}',
                method='POST'
            )
            return "Call transferred."
        except Exception as e:
            return f"Error transferring call: {str(e)}"

    async def end_call(self, context, args):
        from twilio.rest import Client
        account_sid = os.environ['TWILIO_ACCOUNT_SID']
        auth_token = os.environ['TWILIO_AUTH_TOKEN']
        client = Client(account_sid, auth_token)
        call_sid = context.call_sid

        call = client.calls(call_sid).fetch()
        if call.status in ['completed', 'failed', 'busy', 'no-answer', 'canceled']:
            return f"Call already ended with status: {call.status}"

        await asyncio.sleep(5)
        call = client.calls(call_sid).update(status='completed')
        return f"Call ended successfully. Final status: {call.status}"

    # New helper function to detect and handle tool calls
    async def handle_tool_calls(self, response_text: str, interaction_count: int) -> bool:
        # Check for appointment details in the response
        if "appointment" in response_text.lower():
            # Extract date and time using regex
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?)', response_text)
            time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)|\d{2}:\d{2})', response_text)
            
            if date_match or time_match:
                details = {}
                if date_match:
                    # Convert date to standard format
                    try:
                        date_str = date_match.group(1)
                        parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                        details['date'] = parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        try:
                            # Try alternative format
                            parsed_date = datetime.strptime(date_str, '%d %B %Y')
                            details['date'] = parsed_date.strftime('%Y-%m-%d')
                        except ValueError:
                            pass
                
                if time_match:
                    # Convert time to standard format
                    try:
                        time_str = time_match.group(1)
                        parsed_time = datetime.strptime(time_str, '%H:%M')
                        details['time'] = parsed_time.strftime('%H:%M')
                    except ValueError:
                        try:
                            # Try alternative format
                            parsed_time = datetime.strptime(time_str, '%I:%M %p')
                            details['time'] = parsed_time.strftime('%H:%M')
                        except ValueError:
                            pass
                
                if details:
                    self.context.update_appointment_details(details)

        # Check for negative responses to "anything else"
        negative_responses = ["no", "nope", "nahi", "not really", "that's all", "nothing else"]
        if (any(resp in response_text.lower() for resp in negative_responses) and 
            ("anything else" in response_text.lower() or self.context.asked_anything_else)):
            logger.info("User indicated no more questions, ending call")
            self.context.last_response_was_no = True
            await self.emit('llmreply', {
                "partialResponseIndex": None,
                "partialResponse": "Thank you for your time. Looking forward to meeting you!"
            }, interaction_count)
            await asyncio.sleep(2)  # Give time for the closing message
            self.context.mark_conversation_end()
            await self.end_call(self.context, {})
            return True

        # Pattern to detect function calls: [function_name(args)]
        pattern = r'\[(\w+)\((.*?)\)\]'
        matches = re.findall(pattern, response_text)
        
        if not matches:
            # If asking about anything else, mark it
            if "anything else" in response_text.lower():
                self.context.asked_anything_else = True
            return False

        for function_name, args_str in matches:
            if function_name in self.available_functions:
                logger.info(f"Detected tool call: {function_name} with args: {args_str}")
                
                # Prevent duplicate WhatsApp messages
                if function_name == "send_whatsapp" and self.context.whatsapp_sent:
                    logger.info("Skipping duplicate WhatsApp message")
                    await self.emit('llmreply', {
                        "partialResponseIndex": None,
                        "partialResponse": "I've already sent you the confirmation message. Is there anything else I can help you with?"
                    }, interaction_count)
                    self.context.asked_anything_else = True
                    return True

                # Get tool metadata
                tool_data = next((tool for tool in tools if tool['function']['name'] == function_name), None)
                if tool_data:
                    say = tool_data['function']['say']
                    await self.emit('llmreply', {
                        "partialResponseIndex": None,
                        "partialResponse": say
                    }, interaction_count)

                # Execute the function
                function_to_call = self.available_functions[function_name]
                args = self.validate_function_args(args_str)
                function_response = await function_to_call(self.context, args)
                
                logger.info(f"Function {function_name} executed with result: {function_response}")
                
                # Handle WhatsApp response specially
                if function_name == "send_whatsapp":
                    if isinstance(function_response, dict):
                        if function_response.get("success"):
                            self.context.whatsapp_sent = True
                            await self.emit('llmreply', {
                                "partialResponseIndex": None,
                                "partialResponse": "I've sent you the confirmation. Is there anything else I can assist you with?"
                            }, interaction_count)
                            self.context.asked_anything_else = True
                        else:
                            error_msg = function_response.get("error", "Unknown error")
                            await self.emit('llmreply', {
                                "partialResponseIndex": None,
                                "partialResponse": f"I apologize, but I couldn't send the WhatsApp message. {error_msg}"
                            }, interaction_count)
                    return True  # Return True to stop further processing

                # Handle end_call specially
                elif function_name == "end_call":
                    self.context.mark_conversation_end()
                    return True

                # For other functions, append to context and continue
                self.user_context.append({"role": "assistant", "content": say})
                if function_name != "end_call":
                    self.user_context.append({"role": "function", "content": str(function_response), "name": function_name})
                    await self.completion(str(function_response), interaction_count, "function", function_name)
                return True
                
        return False

class GeminiService(AbstractLLMService):
    def __init__(self, context: CallContext):
        super().__init__(context)
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    async def completion(self, text: str, interaction_count: int, role: str = 'user', name: str = 'user'):
        try:
            self.user_context.append({"role": role, "content": text, "name": name})
            
            # Enhanced system message to instruct Gemini about tool usage
            enhanced_system_message = (
                f"{self.system_message}\n\n"
                "IMPORTANT: You MUST use these functions by writing [function_name(args)] in your response:\n"
                "- [transfer_call()] - Transfer the call to another number\n"
                "- [end_call()] - End the current call\n"
                "- [send_whatsapp({\"message\": \"message text\"})] - Send a WhatsApp message. You MUST call this function when confirming appointments.\n\n"
                "Initial Time Request Handling:\n"
                "1. If user says 'no', 'busy', 'not now', 'in a meeting', or indicates they don't have time:\n"
                "   - Respond with: 'Ah, I see. What would be a better time to call you back?'\n"
                "   - After they suggest a time, say: 'Thank you for letting me know. I'll make a note to call you at [their suggested time].'\n"
                "   - End with: 'Have a great day!' and use [end_call()]\n"
                "2. Only proceed with property discussion if they agree to talk\n\n"
                "Appointment Booking Flow:\n"
                "1. First, ask for and confirm the preferred date and time for the site visit\n"
                "2. After date/time is confirmed, ask: 'May I confirm if [number] is your WhatsApp number for sending the appointment details?'\n"
                "3. Only after both date/time AND WhatsApp number are confirmed separately, proceed with sending confirmation\n"
                "4. NEVER assume the phone number is a WhatsApp number without explicit confirmation\n"
                "5. If user only provides date/time, ask about WhatsApp number separately\n"
                "6. If user only confirms WhatsApp number, ask about preferred date/time separately\n\n"
                "WhatsApp Confirmation:\n"
                "1. Only send WhatsApp confirmation after BOTH date/time AND number are explicitly confirmed\n"
                "2. Use this exact format for appointment confirmations:\n"
                "[send_whatsapp({\"message\": \"*SHIVALIK GROUP*\\n*Appointment Confirmation*\\n\\nDear *{name}*,\\n\\nYour site visit has been scheduled for:\\nDate: *{date}*\\nTime: *{time}*\\n\\nLocation:\\nShivalik House, Beside Satellite Police Station,\\nRamdevnagar Cross Road, Satellite Rd,\\nAhmedabad, Gujarat - 380015\\n\\nPlease arrive *10 minutes* before your scheduled time.\\n\\nContact: *Riya* (Shivalik Group)\\nMobile: *+91 79 4020 0000*\\n\\n_We look forward to showing you our premium properties._\"})]\n"
                "3. After sending confirmation, ask if there's anything else you can help with\n\n"
                "IMPORTANT RULES:\n"
                "1. NEVER say you sent a message unless you actually called [send_whatsapp()]\n"
                "2. ALWAYS handle date/time and WhatsApp confirmation as separate steps\n"
                "3. NEVER assume phone number is WhatsApp without explicit confirmation\n"
                "Only use these functions when explicitly requested or clearly appropriate."
            )
            
            messages = []
            for msg in self.user_context:
                messages.append({
                    "role": "user" if msg["role"] == "user" else "model",
                    "parts": [msg["content"]]
                })
            
            prompt = f"System: {enhanced_system_message}\n\n" + "\n".join(
                [f"{msg['role']}: {msg['parts'][0]}" for msg in messages]
            )

            response = await self.model.generate_content_async(
                prompt,
                generation_config={
                    "max_output_tokens": 300,
                    "temperature": 0.7,
                }
            )

            complete_response = response.text
            
            # Check for tool calls first
            if await self.handle_tool_calls(complete_response, interaction_count):
                return

            # If no tool calls, process as regular response
            chunk_size = 50
            for i in range(0, len(complete_response), chunk_size):
                chunk = complete_response[i:i + chunk_size]
                await self.emit_complete_sentences(chunk, interaction_count)

            if self.sentence_buffer.strip():
                await self.emit('llmreply', {
                    "partialResponseIndex": self.partial_response_index,
                    "partialResponse": self.sentence_buffer.strip()
                }, interaction_count)
                self.sentence_buffer = ""

            self.user_context.append({"role": "assistant", "content": complete_response})

        except Exception as e:
            logger.error(f"Error in GeminiService completion: {str(e)}")

class LLMFactory:
    @staticmethod
    def get_llm_service(service_name: str, context: CallContext) -> AbstractLLMService:
        if service_name.lower() == "gemini":
            return GeminiService(context)
        else:
            raise ValueError(f"Unsupported LLM service: {service_name}")