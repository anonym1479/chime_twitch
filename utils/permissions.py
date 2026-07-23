from functools import wraps

def parse_badges(ctx) -> dict:
    """Parses the user's badges from the live Twitch message."""
    badges_tag = ctx.message.tags.get("badges")
    if not badges_tag:
        return {}
    
    result = {}
    for badge_str in badges_tag.split(","):
        parts = badge_str.split("/")
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result

def is_broadcaster(ctx) -> bool:
    """It verifies that the command was sent by the streamer themselves."""
    return ctx.author.name.lower() == ctx.channel.name.lower()

def is_lead_mod(ctx) -> bool:
    """Lead moderator or higher (Streamer)."""
    if is_broadcaster(ctx):
        return True
    badges = parse_badges(ctx)
    return "lead_moderator" in badges or "staff" in badges or "admin" in badges

def is_moderator(ctx) -> bool:
    """Moderator level or higher (Lead Mod, Streamer, or Twitch Mod)."""
    if is_lead_mod(ctx):
        return True
    return getattr(ctx.author, "is_mod", False)

def is_vip(ctx) -> bool:
    """VIP level or higher (Mods, Lead Mods, and Streamers are automatically promoted)."""
    if is_moderator(ctx):
        return True
    badges = parse_badges(ctx)
    return "vip" in badges

def is_subscriber(ctx) -> bool:
    """Subscriber level or higher (including VIPs, mods, and streamers)."""
    if is_vip(ctx):
        return True
    badges = parse_badges(ctx)
    return "subscriber" in badges or "founder" in badges


# --- DECORATORS WITH HIERARCHICAL AUTHORITY ---

def lead_mod_only():
    """For lead moderators and the streamer only."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            if not is_lead_mod(ctx):
                await ctx.send(f"@{ctx.author.name} ❌ This command is available only to lead moderators and the streamer!")
                return
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator

def mod_only():
    """For moderators and those above them (including Lead Mods and streamers)."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            if not is_moderator(ctx):
                await ctx.send(f"@{ctx.author.name} ❌ This command is available only to moderators and those above that level!")
                return
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator

def vip_only():
    """For VIPs and above (including Mods, Lead Mods, and Streamers)."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            if not is_vip(ctx):
                await ctx.send(f"@{ctx.author.name} ❌ This command is available only to VIPs and those above that level!")
                return
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator

def sub_only():
    """Subscribers and those above that level (including VIP, Mod, Lead Mod, and Streamer)."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            if not is_subscriber(ctx):
                await ctx.send(f"@{ctx.author.name} ❌ This command is available only to subscribers!")
                return
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator