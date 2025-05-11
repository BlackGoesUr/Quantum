import random
import re
import hashlib

def scan_message(text):
    """
    Analyze a message and provide a JoJo-themed response.
    This is mostly flavor text but includes some useful analysis.
    """
    if not text:
        return "There's nothing to analyze here."
    
    # Create a hash of the text to ensure consistent results
    text_hash = hashlib.md5(text.encode()).hexdigest()
    hash_int = int(text_hash, 16)
    random.seed(hash_int)

    # Calculate basic text metrics
    word_count = len(text.split())
    char_count = len(text)
    sentence_count = len(re.split(r'[.!?]+', text))
    
    # Sentiment analysis (very basic)
    positive_words = ["good", "great", "awesome", "amazing", "excellent", "happy", "joy", "love", "like", "best"]
    negative_words = ["bad", "worst", "terrible", "horrible", "hate", "dislike", "awful", "poor", "wrong", "sad"]
    
    positive_count = sum(1 for word in re.findall(r'\b\w+\b', text.lower()) if word in positive_words)
    negative_count = sum(1 for word in re.findall(r'\b\w+\b', text.lower()) if word in negative_words)
    
    # Determine sentiment based on counts
    if positive_count > negative_count:
        sentiment = "positive"
    elif negative_count > positive_count:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    
    # Check for questions
    question_marks = text.count('?')
    is_question = question_marks > 0
    
    # Check for exclamations
    exclamation_marks = text.count('!')
    is_excited = exclamation_marks > 0
    
    # Generate JoJo-themed analysis
    jojo_themed_results = [
        f"My Stand, 「HERMIT PURPLE」, reveals this message contains {word_count} words and {char_count} characters!",
        f"Using 「HIEROPHANT GREEN」, I can see this message has {sentence_count} sentences with a {sentiment} tone.",
        f"「STAR PLATINUM」's keen eye notices this message is {'' if is_question else 'not '}asking a question.",
        f"「THE WORLD」stopped time to analyze this message. It appears to be {sentiment} in nature.",
        f"「KILLER QUEEN」has already touched this message! It contains {positive_count} positive and {negative_count} negative words.",
        f"「GOLD EXPERIENCE」breathes life into this analysis: This message is {'' if is_excited else 'not '}written with excitement.",
        f"「CRAZY DIAMOND」can repair anything, but even it can tell this message has a {sentiment} sentiment.",
        f"「KING CRIMSON」has erased the time it took to analyze this message of {word_count} words.",
        f"「MADE IN HEAVEN」accelerated time to quickly determine this message is {sentiment} in nature."
    ]
    
    # Choose multiple insights based on message length
    num_insights = min(3, max(1, len(text) // 50))
    insights = random.sample(jojo_themed_results, num_insights)
    
    # Generate summary
    if sentiment == "positive":
        summary = "This message seems friendly and positive! ✨"
    elif sentiment == "negative":
        summary = "This message has a negative tone. 😡"
    else:
        summary = "This message appears to be neutral in tone. 🤔"
    
    if is_question:
        summary += " It seems to be asking a question."
    if is_excited:
        summary += " The message conveys excitement!"
    
    # Reset random seed
    random.seed()
    
    # Combine results
    result = "\n".join(insights) + f"\n\nStand Conclusion: {summary}"
    return result
