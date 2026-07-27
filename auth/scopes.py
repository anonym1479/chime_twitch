BOT_SCOPES = [
    # EventSub Chat
    "user:read:chat",
    "user:write:chat",
    "user:bot",
    "channel:bot",

    # Backward compatibility (IRC)
    "chat:read",
    "chat:edit",

    # Moderation
    "moderator:manage:chat_messages",

    # Future-proof
    "channel:moderate",
]

SCOPES_STRING = " ".join(BOT_SCOPES)