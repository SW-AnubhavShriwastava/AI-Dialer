import os
import json
import requests
from urllib.parse import quote

async def send_whatsapp(context, args):
    """Send a WhatsApp message to the user's number using the TextMeBot API."""
    try:
        # Get the message from args
        message = args.get('message')
        if not message:
            return {"success": False, "error": "No message provided"}

        # Read user data to get the phone number
        try:
            with open("user_data/user_data.json", "r") as file:
                user_data = json.load(file)
                phone_number = user_data.get("phone_number")
        except Exception as e:
            return {"success": False, "error": f"Error reading user data: {str(e)}"}

        if not phone_number:
            return {"success": False, "error": "No phone number found in user data"}

        # Format phone number - keep the + if it exists, otherwise add it
        phone_number = phone_number.replace(" ", "").replace("-", "")
        if not phone_number.startswith("+"):
            phone_number = "+" + phone_number

        # Remove the + for the API call but keep the country code
        api_phone_number = phone_number[1:] if phone_number.startswith("+") else phone_number

        # Preserve WhatsApp formatting characters while URL encoding the message
        # Replace formatting characters with temporary placeholders
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
        api_url = f"http://api.textmebot.com/send.php?recipient={api_phone_number}&apikey=qS99R1TXcQRV&text={encoded_message}"

        # Send the request
        response = requests.get(api_url)

        if response.status_code == 200:
            # Check if the response contains "Success!" to confirm message was sent
            if "Success!" in response.text:
                return {"success": True, "message": "WhatsApp message sent successfully"}
            else:
                return {"success": False, "error": f"API returned success status but message may not have been sent. Response: {response.text}"}
        else:
            return {"success": False, "error": f"Error sending WhatsApp message. Status code: {response.status_code}, Response: {response.text}"}

    except Exception as e:
        return {"success": False, "error": f"Error in send_whatsapp function: {str(e)}"} 