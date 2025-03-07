import importlib
import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import google.generativeai as genai

from functions.function_manifest import tools
from logger_config import get_logger
from services.call_context import CallContext
from services.event_emmiter import EventEmitter

logger = get_logger("LLMService")

# Define the tools with their metadata
tools = [
    {
        "function": {
            "name": "transfer_call",
            "description": "Transfers the current call to another number",
            "say": "Please hold while I transfer your call.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        "type": "function"
    },
    {
        "function": {
            "name": "end_call",
            "description": "Ends the current call",
            "say": "Goodbye, the call will now end.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        "type": "function"
    }
]

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
            "end_call": self.end_call
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
        # Pattern to detect function calls: [function_name(args)]
        pattern = r'\[(\w+)\((.*?)\)\]'
        matches = re.findall(pattern, response_text)
        
        if not matches:
            return False

        for function_name, args_str in matches:
            if function_name in self.available_functions:
                logger.info(f"Detected tool call: {function_name} with args: {args_str}")
                
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
                
                # Append the function response to context
                self.user_context.append({"role": "assistant", "content": say})
                if function_name != "end_call":
                    self.user_context.append({"role": "function", "content": function_response, "name": function_name})
                    await self.completion(function_response, interaction_count, "function", function_name)
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
                "You can use these functions by writing [function_name(args)] in your response:\n"
                "- [transfer_call()] - Transfer the call to another number\n"
                "- [end_call()] - End the current call\n"
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