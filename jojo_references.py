import random
import hashlib

# JoJo characters for references
JOJO_CHARACTERS = [
    "Jotaro Kujo",
    "Dio Brando",
    "Joseph Joestar",
    "Giorno Giovanna",
    "Josuke Higashikata",
    "Jonathan Joestar",
    "Jolyne Cujoh",
    "Bruno Bucciarati",
    "Speedwagon",
    "Kars",
    "Yoshikage Kira",
    "Diavolo",
    "Enrico Pucci",
    "Lisa Lisa",
    "Polnareff",
    "Kakyoin",
    "Caesar Zeppeli",
    "Avdol",
    "Iggy",
    "Rohan Kishibe"
]

# JoJo quotes for random responses
JOJO_QUOTES = [
    "Yare Yare Daze...",
    "MUDA MUDA MUDA MUDA MUDA!",
    "ORA ORA ORA ORA ORA!",
    "ZA WARUDO!",
    "It was me, DIO!",
    "Your next line is...",
    "OH MY GOD!",
    "NIIIICE!",
    "HOLY SHIIIIT!",
    "WRYYYYYY!",
    "ARRIVEDERCI!",
    "This is... Requiem.",
    "I, Giorno Giovanna, have a dream.",
    "Killer Queen has already touched that doorknob.",
    "Dojyaaa~~n!",
    "Gureto daze!",
    "What a beautiful Duwang, *chew*",
    "MADE IN HEAVEN!",
    "Do you believe in 'gravity'?",
    "I refuse.",
    "Lick, lick, lick, lick, lick, lick, lick, lick, lick, lick, lick, lick, lick, lick...",
    "SHIIIIIZAAAAA!",
    "ROAD ROLLER DA!",
    "EMERALD SPLASH!",
    "Go ahead, Mr. Joestar.",
    "HELL 2 U!",
    "Your ability is no match for my Stand!",
    "Even Speedwagon is afraid!",
    "MUHAMMAD AVDOL! YES, I AM!",
    "STICKY FINGAAAS!",
    "This feels like a picnic."
]

# Stand types and abilities for reference
STAND_TYPES = [
    "Close-Range Power",
    "Long-Range",
    "Automatic",
    "Remote-Control",
    "Bound",
    "Colony",
    "Act",
    "Integrated",
    "Sentient",
    "Time-Based",
    "Dimensional",
    "Reality-Bending"
]

# Comprehensive list of JoJo Stands with their epic quotes
JOJO_STANDS = {
    # Part 3: Stardust Crusaders
    "Star Platinum": {
        "user": "Jotaro Kujo",
        "battle_cry": "ORA ORA ORA ORA ORA ORA ORA!!!",
        "quote": "Good grief... Your Stand is no match for Star Platinum's precision and power.",
        "ability": "Super strength, speed, precision, and time stop"
    },
    "The World": {
        "user": "DIO",
        "battle_cry": "MUDA MUDA MUDA MUDA MUDA MUDA MUDA!!!",
        "quote": "ZA WARUDO! TOKI WO TOMARE! This is the power to reign over this world!",
        "ability": "Time stop"
    },
    "Hierophant Green": {
        "user": "Noriaki Kakyoin",
        "battle_cry": "EMERALD SPLASH!",
        "quote": "No one can just deflect the Emerald Splash!",
        "ability": "Long-range attacks and possession"
    },
    "Silver Chariot": {
        "user": "Jean Pierre Polnareff",
        "battle_cry": "HORA HORA HORA!!!",
        "quote": "My Silver Chariot's blade moves faster than the eye can see!",
        "ability": "Super speed swordsmanship"
    },
    "Magician's Red": {
        "user": "Muhammad Avdol",
        "battle_cry": "CROSSFIRE HURRICANE!",
        "quote": "HELL 2 U! Magician's Red will burn you to ashes!",
        "ability": "Fire manipulation"
    },
    "Hermit Purple": {
        "user": "Joseph Joestar",
        "battle_cry": "OH MY GOD!",
        "quote": "Your next line is... 'How did he know what I was thinking?' Now I'll use Hermit Purple to read your mind!",
        "ability": "Spirit photography and divination"
    },
    "The Fool": {
        "user": "Iggy",
        "battle_cry": "WOOF!",
        "quote": "The Fool is made of sand, you can't hurt what you can't hit!",
        "ability": "Sand manipulation and shapeshifting"
    },

    # Part 4: Diamond is Unbreakable
    "Crazy Diamond": {
        "user": "Josuke Higashikata",
        "battle_cry": "DORA DORA DORA DORA DORA!!!",
        "quote": "WHAT DID YOU SAY ABOUT MY HAIR?! Crazy Diamond will fix your broken face... after I'm done breaking it!",
        "ability": "Restoration and super strength"
    },
    "Killer Queen": {
        "user": "Yoshikage Kira",
        "battle_cry": "Killer Queen has already touched that...",
        "quote": "I just want to live a quiet life. Killer Queen eliminates anything that threatens my peace.",
        "ability": "Explosive touch, Sheer Heart Attack, and Bites The Dust"
    },
    "The Hand": {
        "user": "Okuyasu Nijimura",
        "battle_cry": "OI JOSUKE!",
        "quote": "The Hand can erase anything from existence! Too bad I'm not smart enough to use it properly!",
        "ability": "Space erasure"
    },
    "Echoes": {
        "user": "Koichi Hirose",
        "battle_cry": "S-H-I-T!",
        "quote": "Echoes Act 3! Three Freeze! S-H-I-T!",
        "ability": "Sound effects (Act 1), sound manifestation (Act 2), and gravity manipulation (Act 3)"
    },
    "Heaven's Door": {
        "user": "Rohan Kishibe",
        "battle_cry": "I'll take a look at your reality!",
        "quote": "Heaven's Door! I can read you like an open book and rewrite your actions!",
        "ability": "Reading people as books and rewriting them"
    },

    # Part 5: Golden Wind
    "Gold Experience": {
        "user": "Giorno Giovanna",
        "battle_cry": "MUDA MUDA MUDA MUDA MUDA!!!",
        "quote": "I, Giorno Giovanna, have a dream that I know is just!",
        "ability": "Life creation and enhancement"
    },
    "Gold Experience Requiem": {
        "user": "Giorno Giovanna",
        "battle_cry": "MUDA MUDA MUDA MUDA MUDA MUDA WRYYYYYYY MUDA MUDA!!!",
        "quote": "This is... Requiem. What you're seeing is indeed the truth. You will never arrive at the truth.",
        "ability": "Nullification of cause and effect, infinite death loop"
    },
    "Sticky Fingers": {
        "user": "Bruno Bucciarati",
        "battle_cry": "ARI ARI ARI ARI ARI ARI ARRIVEDERCI!",
        "quote": "The sound of Sticky Fingers creating a zipper... that's the sound of your defeat!",
        "ability": "Creating zippers on any surface"
    },
    "Aerosmith": {
        "user": "Narancia Ghirga",
        "battle_cry": "VOLA VOLA VOLA VOLA VOLAREVOLA!!!",
        "quote": "You can run, but Aerosmith can detect your breathing! VOLARE VIA!",
        "ability": "Miniature airplane with tracking radar"
    },
    "Purple Haze": {
        "user": "Pannacotta Fugo",
        "battle_cry": "UBASHAAAAA!",
        "quote": "One virus capsule from Purple Haze and you'll melt away in seconds!",
        "ability": "Deadly virus production"
    },
    "Sex Pistols": {
        "user": "Guido Mista",
        "battle_cry": "PASS PASS PASS!!!",
        "quote": "My Sex Pistols will guide my bullets to hit you no matter where you hide!",
        "ability": "Bullet manipulation"
    },
    "Moody Blues": {
        "user": "Leone Abbacchio",
        "battle_cry": "REWIND!",
        "quote": "Moody Blues will replay your past actions and reveal your secrets!",
        "ability": "Replay past events"
    },
    "King Crimson": {
        "user": "Diavolo",
        "battle_cry": "It just works!",
        "quote": "King Crimson has erased time and leapt past it! This is my epitaph!",
        "ability": "Time erasure and epitaph prediction"
    },

    # Part 6: Stone Ocean
    "Stone Free": {
        "user": "Jolyne Cujoh",
        "battle_cry": "ORA ORA ORA ORA ORA!!!",
        "quote": "Stone Free! I can unravel myself into string and tie you up!",
        "ability": "Unraveling into string"
    },
    "Whitesnake": {
        "user": "Enrico Pucci",
        "battle_cry": "USELESS USELESS USELESS!",
        "quote": "Whitesnake will steal your Stand and memories, leaving you an empty shell!",
        "ability": "Memory and Stand disc extraction"
    },
    "C-Moon": {
        "user": "Enrico Pucci",
        "battle_cry": "KYOAAAAGH!",
        "quote": "C-Moon inverts gravity itself! The center of gravity is now within me!",
        "ability": "Gravity inversion"
    },
    "Made in Heaven": {
        "user": "Enrico Pucci",
        "battle_cry": "MADE IN HEAVEN!",
        "quote": "Made in Heaven accelerates time toward the new universe! A world of heaven!",
        "ability": "Universal time acceleration"
    },
    "Weather Report": {
        "user": "Weather Report",
        "battle_cry": "Heavy Weather!",
        "quote": "My Weather Report can control any weather phenomenon, even the most destructive!",
        "ability": "Weather manipulation"
    },

    # Part 7: Steel Ball Run
    "Tusk": {
        "user": "Johnny Joestar",
        "battle_cry": "ORA ORA ORA ORA!!!",
        "quote": "Tusk Act 4! Infinite rotation! The power of the Golden Spin!",
        "ability": "Shooting fingernails, dimensional holes, infinite rotation"
    },
    "D4C (Dirty Deeds Done Dirt Cheap)": {
        "user": "Funny Valentine",
        "battle_cry": "Dojyaaan~!",
        "quote": "D4C! I can travel between parallel worlds and bring back alternate versions!",
        "ability": "Parallel world travel and dimensional merging"
    },
    "Scary Monsters": {
        "user": "Diego Brando",
        "battle_cry": "WRYYYYYY!",
        "quote": "Scary Monsters transforms me into the perfect predator! A dinosaur!",
        "ability": "Dinosaur transformation"
    },

    # Part 8: JoJolion
    "Soft & Wet": {
        "user": "Josuke Higashikata (JoJolion)",
        "battle_cry": "ORA ORA ORA ORA!!!",
        "quote": "Soft & Wet! I can take anything from you using these bubbles!",
        "ability": "Stealing properties with bubbles"
    },
    "Wonder of U": {
        "user": "Tooru",
        "battle_cry": "The flow of calamity...",
        "quote": "Calamity befalls those who pursue me. That is the ability of Wonder of U.",
        "ability": "Calamity manipulation"
    }
}

STAND_ABILITIES = [
    "superhuman strength",
    "time manipulation",
    "space distortion",
    "life creation",
    "data manipulation",
    "body transformation",
    "soul manipulation",
    "gravity control",
    "temperature control",
    "sound manipulation",
    "memory alteration",
    "dream infiltration",
    "probability manipulation",
    "healing",
    "luck manipulation",
    "causality reversal",
    "mind reading",
    "illusion creation",
    "invisibility",
    "duplication",
    "elemental control",
    "poison generation",
    "magnetism control",
    "aging manipulation",
    "size alteration",
    "speed boosting",
    "information gathering",
    "reality warping",
    "dimension hopping",
    "object transmutation"
]

def get_random_jojo_quote():
    """Return a random JoJo quote"""
    return random.choice(JOJO_QUOTES)

def get_random_jojo_character():
    """Return a random JoJo character"""
    return random.choice(JOJO_CHARACTERS)

def get_jojo_stand(text):
    """
    Generate a unique Stand ability based on the text input.
    Uses a hash of the text to generate consistent outputs.
    """
    if not text:
        return "This Stand has no abilities yet... It must train harder!"
    
    # Generate a hash from the text for consistent results
    text_hash = hashlib.md5(text.encode()).hexdigest()
    
    # Use the hash to seed the random generator for consistency
    hash_int = int(text_hash, 16)
    random.seed(hash_int)
    
    # Generate stand name (using a pattern like "[something] [something]")
    first_words = ["Star", "Crazy", "Killer", "Golden", "Silver", "Stone", "Sticky", "Spice", "Aerosmith", 
                  "Emperor", "Hierophant", "Dark", "Enigma", "Heaven's", "King", "Pearl", "Magician's", 
                  "Hermit", "Tower", "The", "Purple", "White", "Green", "Red", "Black", "Yellow", "Blue"]
    
    second_words = ["Platinum", "Diamond", "Queen", "Experience", "Chariot", "Free", "Fingers", "Girl", 
                   "Crimson", "Green", "Purple", "Blue", "Door", "White Album", "Pistols", "Jam", 
                   "World", "Moon", "Sun", "Star", "Hand", "Snake", "Sabbath", "Haze", "Requiem"]
    
    stand_name = random.choice(first_words) + " " + random.choice(second_words)
    
    # Generate Stand stats
    stats = ["Power", "Speed", "Range", "Durability", "Precision", "Potential"]
    stand_stats = {stat: random.choice("ABCDE") for stat in stats}
    
    # Select type and abilities
    stand_type = random.choice(STAND_TYPES)
    
    # Number of abilities based on text length (1-3)
    num_abilities = min(3, max(1, len(text) // 20))
    stand_abilities = random.sample(STAND_ABILITIES, num_abilities)
    
    # Create a weakness
    weaknesses = [
        "limited range", 
        "user must remain still",
        "high energy consumption",
        "can only be used for 5 seconds at a time",
        "user takes damage when the Stand is hit",
        "only works in daylight",
        "only works at night",
        "requires the user to hold their breath",
        "user must see the target",
        "user must know the target's name",
        "can only affect one target at a time",
        "powers diminish over time"
    ]
    
    weakness = random.choice(weaknesses)
    
    # Build the description
    description = f"『{stand_name}』\n"
    description += f"Type: {stand_type}\n\n"
    description += "Abilities:\n"
    for ability in stand_abilities:
        description += f"• {ability.capitalize()}\n"
    
    description += f"\nWeakness: {weakness.capitalize()}\n\n"
    
    # Add stats
    description += "Stats:\n"
    for stat, value in stand_stats.items():
        description += f"• {stat}: {value}\n"
    
    # Reset the random seed
    random.seed()
    
    return description
