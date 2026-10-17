"""Server-side administrator permissions, read fresh for every request."""
PRIMARY_ADMIN_EMAIL = "djata.akossiwa@gmail.com"
PERMISSION_MODULES = {
    "pilotage": "Pilotage national (indicateurs consolidés)",
    "comptes": "Comptes utilisateurs",
    "revendeurs": "Revendeurs, coordonnées et dernière vente",
    "analyses": "Analyses commerciales et objectifs",
    "performances": "Performances et primes",
    "difficultes": "Difficultés des revendeurs",
    "donnees": "Détail des ventes et stocks",
    "audit": "Journal des opérations (toutes rubriques)",
    "notifications": "Historique des notifications (toutes rubriques)",
    "systeme": "État technique du service",
}
EDITABLE = {"comptes", "analyses", "performances", "difficultes", "notifications"}
ALL_PERMISSIONS = [f"{key}.view" for key in PERMISSION_MODULES] + [f"{key}.edit" for key in sorted(EDITABLE)]


def is_primary_admin(user):
    return bool(user and user.role == "administrateur" and user.email.strip().lower() == PRIMARY_ADMIN_EMAIL)


def effective_permissions(user):
    if not user or user.role != "administrateur":
        return []
    if is_primary_admin(user):
        return list(ALL_PERMISSIONS)
    # Existing accounts retain their previous access until the owner configures them.
    return list(ALL_PERMISSIONS) if user.admin_permissions is None else user.admin_permissions


def has_permission(user, permission):
    return permission in effective_permissions(user)


def notification_visible(user, notification):
    if not user or not user.active:
        return False
    if user.role != "administrateur":
        return True
    if notification.kind == "difficulte" or "difficult" in (notification.link or ""):
        return has_permission(user, "difficultes.view")
    if notification.kind == "vente":
        return has_permission(user, "donnees.view")
    if notification.kind == "prime":
        return has_permission(user, "performances.view")
    return is_primary_admin(user)
