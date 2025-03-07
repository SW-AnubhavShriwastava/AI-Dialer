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
            "say": "Well then, thank you so much for your time. It was a pleasure speaking with you. Have a great day!",
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
            "name": "send_whatsapp",
            "description": "Sends a WhatsApp message to the user's number",
            "say": "Great, I'll send you the appointment details over WhatsApp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to send"
                    }
                },
                "required": ["message"]
            }
        },
        "type": "function"
    }
]
