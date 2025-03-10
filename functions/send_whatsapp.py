import os
import json
import requests
from urllib.parse import quote
import re
from typing import Optional

def validate_phone_number(phone: str) -> tuple[bool, Optional[str]]:
    """Validate phone number format."""
    # Remove any spaces, dashes, or parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Check if it starts with + and has 10-15 digits
    if re.match(r'^\+\d{10,15}$', cleaned):
        return True, cleaned
    
    # If no +, check if it has 10-15 digits
    if re.match(r'^\d{10,15}$', cleaned):
        return True, f"+{cleaned}"
        
    return False, None

async def send_whatsapp(context, args):
    """Send a WhatsApp message to the user's number using the TextMeBot API."""
    try:
        # Get the message from args
        message = args.get('message')
        if not message:
            return {"success": False, "error": "No message provided"}

        # Format message with context details
        try:
            message = message.format(
                name=context.user_name,
                date=context.appointment_date,
                time=context.appointment_time,
                property=context.property_of_interest or "our properties"
            )
        except KeyError as e:
            return {"success": False, "error": f"Missing required detail: {str(e)}"}

        # Read and validate phone number
        try:
            with open("user_data/user_data.json", "r") as file:
                user_data = json.load(file)
                phone_number = user_data.get("phone_number")
        except Exception as e:
            return {"success": False, "error": f"Error reading user data: {str(e)}"}

        if not phone_number:
            return {"success": False, "error": "No phone number found in user data"}

        # Validate phone number format
        is_valid, formatted_number = validate_phone_number(phone_number)
        if not is_valid:
            return {"success": False, "error": "Invalid phone number format"}

        # Remove the + for the API call but keep the country code
        api_phone_number = formatted_number[1:] if formatted_number.startswith("+") else formatted_number

        # Preserve WhatsApp formatting characters while URL encoding the message
        formatting_chars = {
            "*": "{{ASTERISK}}",
            "_": "{{UNDERSCORE}}",
            "\n": "{{NEWLINE}}"
        }
        
        formatted_message = message
        for char, placeholder in formatting_chars.items():
            formatted_message = formatted_message.replace(char, placeholder)
            
        # URL encode the message
        encoded_message = quote(formatted_message)
        
        # Restore formatting characters
        for char, placeholder in formatting_chars.items():
            encoded_message = encoded_message.replace(quote(placeholder), char)

        # Construct the API URL
        api_url = f"http://api.textmebot.com/send.php?recipient={api_phone_number}&apikey=yfNpxXSksHFQ&text={encoded_message}"

        # Send the request with retry mechanism
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                response = requests.get(api_url, timeout=10)
                if response.status_code == 200 and "Success!" in response.text:
                    # Update context
                    context.whatsapp_sent = True
                    return {"success": True, "message": "WhatsApp message sent successfully"}
                elif response.status_code == 200:
                    retry_count += 1
                    if retry_count == max_retries:
                        return {"success": False, "error": f"API returned success status but message may not have been sent. Response: {response.text}"}
                else:
                    retry_count += 1
                    if retry_count == max_retries:
                        return {"success": False, "error": f"Error sending WhatsApp message. Status code: {response.status_code}, Response: {response.text}"}
            except requests.RequestException as e:
                retry_count += 1
                if retry_count == max_retries:
                    return {"success": False, "error": f"Network error while sending WhatsApp message: {str(e)}"}

    except Exception as e:
        return {"success": False, "error": f"Error in send_whatsapp function: {str(e)}"} 