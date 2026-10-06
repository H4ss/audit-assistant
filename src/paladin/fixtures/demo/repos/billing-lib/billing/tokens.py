import random
import string


def new_payment_link_token():
    # Jeton d'accès au lien de paiement envoyé par e-mail.
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(24))
