import re
import os

class ProfanityFilter:
    """
    A class for filtering profanity from text messages.
    Uses regex patterns to catch bypass attempts.
    """
    
    def __init__(self):
        # Base list of profanity words
        self.profanity_words = [
            # Original list
            "fuck", "shit", "bitch", "cunt", "dick", "cock", "pussy", "asshole", "whore",
            "slut", "bastard", "damn", "nigger", "nigga", "niger", "n1gger", "n1gga", "retard", "faggot", "fag",
            "nazi", "kike", "chink", "spic", "porn", "sex", "penis", "vagina", "ass",
            
            # Extended list (organized alphabetically)
            "@buse", "@ss", "a$$", "abuse", "animal ka", "ape", "arse", 
            "b!tch", "b!tch$", "b0b0", "b1tch", "b1tch$", "basterd", "bayut", "b**bs", 
            "bich", "bj", "bjay", "blowjob", "bob0", "bobo", "bomb", "boobs", "b*tch", 
            "btch", "bwisit", "b*yut", 
            "c#nk", "c0ck", "c*ck", "ch!n", "ch!nk", "ch!n*k", "ch@nk", "ch1ld molester", 
            "ch1nk", "ch1n*k", "child molester", "child porn", "c*hild porn", "ch*ld molester", 
            "ch*ld p0rn", "ch*nk", "c*m", "cracker", "cum", "cut myself", 
            "d1ck", "dam", "d*ck", "d*e", "d*mn", "dmn", "dumbass", 
            "f.u.c.k", "f@ck", "f@g", "f@gger", "f@gget", "f@ggot", "f@got", "f4ggot", 
            "f*ck", "fck", "f*g", "f*gg", "f*ggot", "fuk", "fuxk", 
            "g!psy", "g1psy", "gaga", "gaga ka", "gago", "gago ka", "g*go", "go die", "g*psy", 
            "gyp$y", "gypsy", 
            "h3ll", "hayop ka", "h*e", "hell", "hentai", "hindot", "hind*t", "hindutan", 
            "jizz", 
            "k!ke", "k@ke", "k0ke", "k1ke", "k1ll", "kabaklaan", "k*ke", "k*ke$", "k*ll", "k*nt", 
            "lantarang kabastusan", "leche", "lintik",
            "m0lest", "makibaka", "m*l3st", "m*lest", "m*l*st", "monkey", 
            "n!gga", "n!gger", "n@gga", "n@gger", "n€gger", "n0gga", "n0gger", "n1gga", "n1gger", 
            "n3gg3r", "n3gga", "n*gga", "n*gger", "nsfw", "nude", "nudes", 
            "p-uta", "p-utangina", "p@ta", "p0rn", "p3do", "p3dophile", "pakyu", "pakyu ka", 
            "paq you", "paqyu", "p*d0", "p*do", "p*dophile", "p*doporn", "pedo", "pedophile", 
            "peste", "p*k", "p*k yu", "p*kyu", "p*kyu ka", "p*nis", "p*rn", "p*ssy", "p*ssy$", 
            "p*sty", "p*ta", "p*tangina", "pussi", "put*", "puta", "putang ina", "putang-ina", 
            "putangina", "put*ngina", 
            "r@pe", "r4pe", "rapist", "rap*st", "r*pe", "r*pist", "r*tard", 
            "s.hit", "s3x", "sandn!gga", "sandn@gga", "sandn@gger", "sandn*gger", "selfharm", 
            "sh*t", "sht", "sl*t", "sp!c", "sp@c", "sp0c", "sp1c", "sp*c", "sp*c$", "s*x", 
            "t!nny", "t@nga", "t0welhead", "tang-ina", "tanga", "tangina", "tangina mo", 
            "tanginamo", "t*anny", "tarantado", "terrorist", "tits", "t*nga", "t*ngina", 
            "towelhead", "tr@nn@", "tr@nny", "tr4nny", "tranny", "tr*nny", "t*ts", "t*welh3ad", 
            "t*welhead", 
            "ul*l", "ulol", 
            "walang hiya", "walanghiya", "wh*re"
        ]
        
        # Additional keywords related to harassment
        self.harassment_words = [
            "kill yourself", "kys", "suicide", "hang yourself", "end yourself",
            "rape", "raping", "molest", "molesting", "sexual", "pedophile", 
            "die", "hang", "neck yourself"
        ]
        
        # Compile all words into regex patterns to catch bypasses
        self.compile_regex_patterns()
    
    def compile_regex_patterns(self):
        """Compile regex patterns for each word to catch bypass attempts"""
        self.patterns = []
        
        # Process all profanity words
        for word in self.profanity_words + self.harassment_words:
            # Basic pattern to catch the word itself
            pattern = r'\b'
            
            # For each character in the word, create a pattern that matches:
            # - The character itself
            # - Common substitutions (e.g., 'a' can be '@', '4', etc.)
            # - Optional spaces or symbols between characters
            for char in word:
                if char == 'a':
                    pattern += r'[a@4àáâäãåą∆Д]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'b':
                    pattern += r'[b8ßвь]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'c':
                    pattern += r'[c¢çćčс©]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'd':
                    pattern += r'[dđďð]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'e':
                    pattern += r'[e3èéêëęėξεЕ€]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'f':
                    pattern += r'[fƒ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'g':
                    pattern += r'[g6ğģ9]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'h':
                    pattern += r'[hħнΗн]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'i':
                    pattern += r'[i1!¡íìîïįιΙ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'j':
                    pattern += r'[jјĵ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'k':
                    pattern += r'[kķĸκк]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'l':
                    pattern += r'[l1|!łлιL£]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'm':
                    pattern += r'[mмΜ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'n':
                    pattern += r'[nñнηИΝЛ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'o':
                    pattern += r'[o0òóôõöøөΟο☺☻⚪⚫]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'p':
                    pattern += r'[pрρРπп♀]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'q':
                    pattern += r'[q9]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'r':
                    pattern += r'[rгř®яЯ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 's':
                    pattern += r'[s5$śšşѕ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 't':
                    pattern += r'[t7+тτТт†‡]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'u':
                    pattern += r'[uüúùûụųμυµ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'v':
                    pattern += r'[v\/υνν♈]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'w':
                    pattern += r'[wшщẁẃẅwω]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'x':
                    pattern += r'[x×хжж✗✘χ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'y':
                    pattern += r'[yýÿчụγ¥λΥ]+[\s\*\.\-_\(\)\'\"]*'
                elif char == 'z':
                    pattern += r'[zžżźзж2]+[\s\*\.\-_\(\)\'\"]*'
                elif char == ' ':
                    pattern += r'[\s\*\.\-_\(\)\'\"]*'
                else:
                    pattern += r'[' + re.escape(char) + r']+[\s\*\.\-_\(\)\'\"]*'
            
            pattern += r'\b'
            try:
                self.patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                # If there's an error compiling the regex, use a simpler version
                simple_pattern = r'\b' + ''.join([char + r'[\s\*\.\-_]*' for char in word]) + r'\b'
                self.patterns.append(re.compile(simple_pattern, re.IGNORECASE))
    
    def contains_profanity(self, text):
        """
        Check if the text contains any profanity or harassment words.
        Returns True if profanity is found, False otherwise.
        """
        if not text:
            return False
        
        # Check each pattern against the text
        for pattern in self.patterns:
            if pattern.search(text):
                return True
        
        return False
    
    def censor_text(self, text):
        """
        Censor profanity in the text by replacing it with asterisks.
        Returns the censored text.
        """
        if not text:
            return text
        
        censored_text = text
        
        # Replace each match with asterisks
        for pattern in self.patterns:
            censored_text = pattern.sub(lambda match: '*' * len(match.group(0)), censored_text)
        
        return censored_text
