# Households & Members

Households, their members, and each member's dietary profile live on the **Core API**, so
they use the **`Client`** class — not `DataClient`. The object model here is simpler than
the Data API's entity/proxy system: plain objects whose property setters auto-sync to the
API.

```python
from wisefood import Client, Credentials   # note: Client, not DataClient
```

## Create a Core API client

```python
import os
from wisefood import Client, Credentials

client = Client(
    os.environ["WISEFOOD_CORE_URL"],   # e.g. https://api.wisefood.example
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)
```

## Households

```python
# The household owned by the authenticated user
household = client.households.me()
print(household.name, household.region)

# By id, or list (admin)
household = client.households.get("household-id-123")
all_households = client.households.list(limit=50, offset=0)

# Create
household = client.households.create(
    name="The Smith Family",
    region="US-CA",
    members=[{"name": "John", "age_group": "adult"}],
)

# Update — property setters auto-sync to the API
household.name = "The Smith-Jones Family"
household.region = "US-NY"

# ...or via the proxy
client.households.update("household-id-123", name="New Name")

# Delete
client.households.delete("household-id-123")
```

## Members

```python
# All members of a household
members = household.members
for m in members:
    print(m.name, m.age_group)

# Add a member to this household
member = household.add_member(name="Alex", age_group="adult")

# Or through the members proxy
member = client.members.create(
    household_id=household.id,
    name="Bob",
    age_group="child",
)

# Fetch / list / delete
member = client.members.get("member-id-123")
members = client.members.list(household_id=household.id, limit=10, offset=0)
client.members.delete("member-id-123")

# Member property setters auto-sync
member.name = "Alexandra"
member.age_group = "young_adult"
member.image_url = "https://example.com/avatar.jpg"
```

## Member profiles

Each member has a **profile** holding dietary information. Accessing `member.profile`
fetches it on first use; assigning a profile attribute auto-syncs it back.

```python
profile = member.profile

profile.dietary_groups = ["vegetarian", "gluten_free"]
profile.allergies = ["shellfish", "sesame"]
profile.nutritional_preferences = {
    "calories": 2000,
    "protein": 50,
    "food_likes": ["beef", "yogurt", "quinoa"],
    "food_dislikes": ["spinach", "oats"],
}
profile.properties = {
    "feedback_history": "the user likes pizza",
    "liked_recipes": [1, 2, 3],
}
```

Unset list fields read back as `[]` and dict fields as `{}`, so you can read before
writing without guarding for `None`.

## Worked example

```python
import os
from wisefood import Client, Credentials

client = Client(
    os.environ["WISEFOOD_CORE_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)

household = client.households.me()
member = household.add_member(name="Alex", age_group="adult")

member.profile.dietary_groups = ["vegetarian", "gluten_free"]
member.profile.allergies = ["shellfish"]

print(f"{member.name}: {member.profile.dietary_groups}")
```

## Reference: age groups

```text
baby · child · teen · young_adult · adult · middle_aged · senior
```

## Reference: dietary groups

```text
omnivore, vegetarian, lacto_vegetarian, ovo_vegetarian, lacto_ovo_vegetarian,
pescatarian, vegan, raw_vegan, plant_based, flexitarian,
halal, kosher, jain, buddhist_vegetarian,
gluten_free, nut_free, peanut_free, dairy_free, egg_free,
soy_free, shellfish_free, fish_free, sesame_free,
low_carb, low_fat, low_sodium, sugar_free, no_added_sugar,
high_protein, high_fiber, low_cholesterol, low_calorie,
keto, paleo, whole30, mediterranean, diabetic_friendly
```

## Gotchas

- Use **`Client`**, not `DataClient`, and point it at the **Core API** base URL.
- Auto-sync issues **one PATCH per assignment**. To change several profile fields at
  once, assign each whole value (each is a single request); group your updates so you
  don't fire more requests than necessary.
- `household.members`, `member.profile`, etc. require the object to be bound to a client
  (objects returned by the proxies already are).
```
