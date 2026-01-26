import pytest

from wisefood.entities.households import (
    Household,
    HouseholdMember,
    HouseholdMemberProfile,
    HouseholdsProxy,
    MembersProxy,
)

from conftest import DummyClient, StubResponse


# ---------------------------------------------------------------------------
# HouseholdMemberProfile Tests
# ---------------------------------------------------------------------------


def test_profile_from_dict():
    data = {
        "dietary_groups": ["vegetarian", "gluten_free"],
        "nutritional_preferences": {"calories": 2000},
        "properties": {"notes": "Test"},
    }
    profile = HouseholdMemberProfile.from_dict(data)

    assert profile.dietary_groups == ["vegetarian", "gluten_free"]
    assert profile.nutritional_preferences == {"calories": 2000}
    assert profile.properties == {"notes": "Test"}


def test_profile_defaults_for_missing_fields():
    profile = HouseholdMemberProfile(data={})

    assert profile.dietary_groups == []
    assert profile.nutritional_preferences == {}
    assert profile.properties == {}


def test_profile_to_dict():
    data = {
        "dietary_groups": ["vegan"],
        "nutritional_preferences": {"protein": 50},
        "properties": {},
    }
    profile = HouseholdMemberProfile(data=data)

    assert profile.to_dict() == data


def test_profile_setattr_marks_dirty_and_syncs(dummy_client: DummyClient):
    dummy_client.queue_response(
        "patch",
        "members/member-123/profile",
        StubResponse(200, {"result": {"dietary_groups": ["vegan"]}}),
    )

    profile = HouseholdMemberProfile(
        client=dummy_client,
        member_id="member-123",
        data={"dietary_groups": []},
        sync=True,
    )

    profile.dietary_groups = ["vegan"]

    # Should have made a PATCH call
    assert len(dummy_client.calls) == 1
    method, endpoint, body, _ = dummy_client.calls[0]
    assert method == "patch"
    assert endpoint == "members/member-123/profile"
    assert body == {"dietary_groups": ["vegan"]}


def test_profile_setattr_no_sync_when_disabled(dummy_client: DummyClient):
    profile = HouseholdMemberProfile(
        client=dummy_client,
        member_id="member-123",
        data={},
        sync=False,
    )

    profile.dietary_groups = ["vegan"]

    # No API call should be made
    assert len(dummy_client.calls) == 0
    # But data should be updated locally
    assert profile.dietary_groups == ["vegan"]


def test_profile_refresh(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "members/member-123/profile",
        StubResponse(200, {"result": {"dietary_groups": ["updated"]}}),
    )

    profile = HouseholdMemberProfile(
        client=dummy_client,
        member_id="member-123",
        data={"dietary_groups": ["old"]},
    )

    profile.refresh()

    assert profile.dietary_groups == ["updated"]


def test_profile_delete(dummy_client: DummyClient):
    profile = HouseholdMemberProfile(
        client=dummy_client,
        member_id="member-123",
        data={"dietary_groups": ["vegan"]},
    )

    profile.delete()

    assert ("delete", "members/member-123/profile", {}) in dummy_client.calls
    assert profile.to_dict() == {}


# ---------------------------------------------------------------------------
# HouseholdMember Tests
# ---------------------------------------------------------------------------


def test_member_from_dict(dummy_client: DummyClient):
    data = {
        "id": "member-123",
        "name": "John",
        "age_group": "adult",
        "household_id": "household-456",
        "image_url": "https://example.com/avatar.png",
        "created_at": "2024-01-01T00:00:00Z",
    }
    member = HouseholdMember.from_dict(data, dummy_client)

    assert member.id == "member-123"
    assert member.name == "John"
    assert member.age_group == "adult"
    assert member.household_id == "household-456"
    assert member.image_url == "https://example.com/avatar.png"


def test_member_property_setters_sync(dummy_client: DummyClient):
    dummy_client.queue_response(
        "patch",
        "members/member-123",
        StubResponse(200, {"result": {"id": "member-123", "name": "Jane"}}),
    )

    member = HouseholdMember(
        client=dummy_client,
        data={"id": "member-123", "name": "John", "age_group": "adult", "household_id": "h1"},
    )

    member.name = "Jane"

    method, endpoint, body, _ = dummy_client.calls[0]
    assert method == "patch"
    assert endpoint == "members/member-123"
    assert body == {"name": "Jane"}


def test_member_profile_property_fetches_on_access(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "members/member-123/profile",
        StubResponse(200, {"result": {"dietary_groups": ["vegetarian"]}}),
    )

    member = HouseholdMember(
        client=dummy_client,
        data={"id": "member-123", "name": "John", "age_group": "adult", "household_id": "h1"},
    )

    profile = member.profile

    assert profile.dietary_groups == ["vegetarian"]
    # Second access should not make another API call
    _ = member.profile
    assert len(dummy_client.calls) == 1


def test_member_profile_auto_syncs_on_change(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "members/member-123/profile",
        StubResponse(200, {"result": {"dietary_groups": []}}),
    )
    dummy_client.queue_response(
        "patch",
        "members/member-123/profile",
        StubResponse(200, {"result": {"dietary_groups": ["vegan"]}}),
    )

    member = HouseholdMember(
        client=dummy_client,
        data={"id": "member-123", "name": "John", "age_group": "adult", "household_id": "h1"},
    )

    member.profile.dietary_groups = ["vegan"]

    # Should have GET (fetch profile) + PATCH (update)
    assert len(dummy_client.calls) == 2
    assert dummy_client.calls[0][0] == "get"
    assert dummy_client.calls[1][0] == "patch"


def test_member_refresh(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "members/member-123",
        StubResponse(200, {"result": {"id": "member-123", "name": "Updated", "age_group": "adult", "household_id": "h1"}}),
    )

    member = HouseholdMember(
        client=dummy_client,
        data={"id": "member-123", "name": "Old", "age_group": "adult", "household_id": "h1"},
    )

    member.refresh()

    assert member.name == "Updated"


def test_member_delete(dummy_client: DummyClient):
    member = HouseholdMember(
        client=dummy_client,
        data={"id": "member-123", "name": "John", "age_group": "adult", "household_id": "h1"},
    )

    member.delete()

    assert ("delete", "members/member-123", {}) in dummy_client.calls


# ---------------------------------------------------------------------------
# Household Tests
# ---------------------------------------------------------------------------


def test_household_from_dict(dummy_client: DummyClient):
    data = {
        "id": "household-123",
        "name": "My Family",
        "owner_id": "user-456",
        "region": "US",
        "metadata": {"plan": "premium"},
    }
    household = Household.from_dict(data, dummy_client)

    assert household.id == "household-123"
    assert household.name == "My Family"
    assert household.owner_id == "user-456"
    assert household.region == "US"
    assert household.metadata == {"plan": "premium"}


def test_household_property_setters_sync(dummy_client: DummyClient):
    dummy_client.queue_response(
        "patch",
        "households/household-123",
        StubResponse(200, {"result": {"id": "household-123", "name": "New Name"}}),
    )

    household = Household(
        client=dummy_client,
        data={"id": "household-123", "name": "Old Name", "owner_id": "user-1"},
    )

    household.name = "New Name"

    method, endpoint, body, _ = dummy_client.calls[0]
    assert method == "patch"
    assert endpoint == "households/household-123"
    assert body == {"name": "New Name"}


def test_household_members_property(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "members",
        StubResponse(200, {"result": [
            {"id": "m1", "name": "Alice", "age_group": "adult", "household_id": "household-123"},
            {"id": "m2", "name": "Bob", "age_group": "child", "household_id": "household-123"},
        ]}),
    )

    household = Household(
        client=dummy_client,
        data={"id": "household-123", "name": "Family", "owner_id": "user-1"},
    )

    members = household.members

    assert len(members) == 2
    assert members[0].name == "Alice"
    assert members[1].name == "Bob"


def test_household_add_member(dummy_client: DummyClient):
    dummy_client.queue_response(
        "post",
        "members",
        StubResponse(200, {"result": {"id": "new-member", "name": "Charlie", "age_group": "teen", "household_id": "household-123"}}),
    )

    household = Household(
        client=dummy_client,
        data={"id": "household-123", "name": "Family", "owner_id": "user-1"},
    )

    member = household.add_member("Charlie", "teen")

    assert member.id == "new-member"
    assert member.name == "Charlie"
    assert member.age_group == "teen"

    method, endpoint, body, _ = dummy_client.calls[0]
    assert method == "post"
    assert endpoint == "members"
    assert body["name"] == "Charlie"
    assert body["age_group"] == "teen"
    assert body["household_id"] == "household-123"


def test_household_refresh(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "households/household-123",
        StubResponse(200, {"result": {"id": "household-123", "name": "Updated", "owner_id": "user-1"}}),
    )

    household = Household(
        client=dummy_client,
        data={"id": "household-123", "name": "Old", "owner_id": "user-1"},
    )

    household.refresh()

    assert household.name == "Updated"


def test_household_delete(dummy_client: DummyClient):
    household = Household(
        client=dummy_client,
        data={"id": "household-123", "name": "Family", "owner_id": "user-1"},
    )

    household.delete()

    assert ("delete", "households/household-123", {}) in dummy_client.calls


# ---------------------------------------------------------------------------
# HouseholdsProxy Tests
# ---------------------------------------------------------------------------


def test_households_proxy_me(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "households/me",
        StubResponse(200, {"result": {"id": "h1", "name": "My Home", "owner_id": "user-1"}}),
    )

    proxy = HouseholdsProxy(dummy_client)
    household = proxy.me()

    assert household.id == "h1"
    assert household.name == "My Home"


def test_households_proxy_get(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "households/h123",
        StubResponse(200, {"result": {"id": "h123", "name": "Family", "owner_id": "user-1"}}),
    )

    proxy = HouseholdsProxy(dummy_client)
    household = proxy.get("h123")

    assert household.id == "h123"


def test_households_proxy_list(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "households",
        StubResponse(200, {"result": [
            {"id": "h1", "name": "Family 1", "owner_id": "u1"},
            {"id": "h2", "name": "Family 2", "owner_id": "u2"},
        ]}),
    )

    proxy = HouseholdsProxy(dummy_client)
    households = proxy.list()

    assert len(households) == 2
    assert households[0].name == "Family 1"
    assert households[1].name == "Family 2"


def test_households_proxy_create(dummy_client: DummyClient):
    dummy_client.queue_response(
        "post",
        "households",
        StubResponse(200, {"result": {"id": "new-h", "name": "New Family", "owner_id": "user-1"}}),
    )

    proxy = HouseholdsProxy(dummy_client)
    household = proxy.create(name="New Family", region="US")

    assert household.id == "new-h"
    assert household.name == "New Family"

    method, endpoint, body, _ = dummy_client.calls[0]
    assert method == "post"
    assert body["name"] == "New Family"
    assert body["region"] == "US"


def test_households_proxy_delete(dummy_client: DummyClient):
    proxy = HouseholdsProxy(dummy_client)
    proxy.delete("h123")

    assert ("delete", "households/h123", {}) in dummy_client.calls


# ---------------------------------------------------------------------------
# MembersProxy Tests
# ---------------------------------------------------------------------------


def test_members_proxy_get(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "members/m123",
        StubResponse(200, {"result": {"id": "m123", "name": "John", "age_group": "adult", "household_id": "h1"}}),
    )

    proxy = MembersProxy(dummy_client)
    member = proxy.get("m123")

    assert member.id == "m123"
    assert member.name == "John"


def test_members_proxy_list(dummy_client: DummyClient):
    dummy_client.queue_response(
        "get",
        "members",
        StubResponse(200, {"result": [
            {"id": "m1", "name": "Alice", "age_group": "adult", "household_id": "h1"},
            {"id": "m2", "name": "Bob", "age_group": "child", "household_id": "h1"},
        ]}),
    )

    proxy = MembersProxy(dummy_client)
    members = proxy.list(household_id="h1")

    assert len(members) == 2
    assert members[0].name == "Alice"


def test_members_proxy_create(dummy_client: DummyClient):
    dummy_client.queue_response(
        "post",
        "members",
        StubResponse(200, {"result": {"id": "new-m", "name": "Charlie", "age_group": "teen", "household_id": "h1"}}),
    )

    proxy = MembersProxy(dummy_client)
    member = proxy.create(household_id="h1", name="Charlie", age_group="teen")

    assert member.id == "new-m"
    assert member.name == "Charlie"


def test_members_proxy_delete(dummy_client: DummyClient):
    proxy = MembersProxy(dummy_client)
    proxy.delete("m123")

    assert ("delete", "members/m123", {}) in dummy_client.calls
