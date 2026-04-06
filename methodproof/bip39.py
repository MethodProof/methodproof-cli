"""BIP39 mnemonic encoding — 128-bit entropy to 12-word recovery phrase."""

import hashlib


def entropy_to_phrase(entropy: bytes) -> str:
    """Encode 16 bytes (128 bits) as 12 BIP39 words with checksum."""
    from methodproof.wordlist import WORDS
    if len(entropy) != 16:
        raise ValueError("Expected 16 bytes of entropy")
    checksum = hashlib.sha256(entropy).digest()[0] >> 4  # 4 bits
    bits = int.from_bytes(entropy) << 4 | checksum  # 132 bits
    words = []
    for _ in range(12):
        words.append(WORDS[bits & 0x7FF])
        bits >>= 11
    return " ".join(reversed(words))


def phrase_to_entropy(phrase: str) -> bytes:
    """Decode 12 BIP39 words back to 16 bytes of entropy."""
    from methodproof.wordlist import WORDS
    word_list = phrase.strip().lower().split()
    if len(word_list) != 12:
        raise ValueError("Expected 12 words")
    index = {w: i for i, w in enumerate(WORDS)}
    bits = 0
    for word in word_list:
        if word not in index:
            raise ValueError(f"Unknown word: {word}")
        bits = (bits << 11) | index[word]
    checksum = bits & 0xF
    entropy = (bits >> 4).to_bytes(16)
    expected = hashlib.sha256(entropy).digest()[0] >> 4
    if checksum != expected:
        raise ValueError("Invalid checksum")
    return entropy
