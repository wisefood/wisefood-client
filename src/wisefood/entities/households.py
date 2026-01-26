"""
Household and HouseholdMember entities and proxies for the WiseFood API.
"""

from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..api_client import Client


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class HouseholdMemberProfile:
    """
    Profile information for a household member.

    Setting properties automatically syncs to the API when sync=True.

    Example:
        >>> member.profile.dietary_groups = ["vegetarian", "gluten_free"]
        >>> member.profile.nutritional_preferences = {"calories": 2000}
    """

    def __init__(
        self,
        client: Optional["Client"] = None,
        member_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        sync: bool = True,
    ):
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_member_id", member_id)
        object.__setattr__(self, "_data", data or {})
        object.__setattr__(self, "_sync", sync)
        object.__setattr__(self, "_dirty_fields", set())

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        client: Optional["Client"] = None,
        member_id: Optional[str] = None,
    ) -> "HouseholdMemberProfile":
        return cls(client=client, member_id=member_id, data=data)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        data = object.__getattribute__(self, "_data")
        if name in data:
            return data[name]
        # Return empty defaults for known fields
        if name == "dietary_groups":
            return []
        if name in ("nutritional_preferences", "properties"):
            return {}
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        data = object.__getattribute__(self, "_data")
        dirty = object.__getattribute__(self, "_dirty_fields")
        sync = object.__getattribute__(self, "_sync")

        data[name] = value
        dirty.add(name)

        if sync:
            self.save()

    def save(self) -> None:
        """Persist changes to the API."""
        client = object.__getattribute__(self, "_client")
        member_id = object.__getattribute__(self, "_member_id")
        data = object.__getattribute__(self, "_data")
        dirty = object.__getattribute__(self, "_dirty_fields")

        if not client or not member_id:
            return

        if not dirty:
            return

        # Send only dirty fields
        payload = {k: data[k] for k in dirty if k in data}
        resp = client.patch(f"members/{member_id}/profile", json=payload)
        new_data = resp.json().get("result", resp.json())
        object.__setattr__(self, "_data", new_data)
        dirty.clear()

    def refresh(self) -> None:
        """Reload profile data from the API."""
        client = object.__getattribute__(self, "_client")
        member_id = object.__getattribute__(self, "_member_id")

        if not client or not member_id:
            raise RuntimeError("Profile not bound to a client")

        resp = client.get(f"members/{member_id}/profile")
        data = resp.json().get("result", resp.json())
        object.__setattr__(self, "_data", data)
        object.__getattribute__(self, "_dirty_fields").clear()

    def delete(self) -> None:
        """Delete this profile from the API."""
        client = object.__getattribute__(self, "_client")
        member_id = object.__getattribute__(self, "_member_id")

        if not client or not member_id:
            raise RuntimeError("Profile not bound to a client")

        client.delete(f"members/{member_id}/profile")
        object.__setattr__(self, "_data", {})

    def to_dict(self) -> Dict[str, Any]:
        return dict(object.__getattribute__(self, "_data"))

    def __repr__(self) -> str:
        data = object.__getattribute__(self, "_data")
        return f"HouseholdMemberProfile({data})"


class HouseholdMember:
    """
    A member of a household.

    Access the profile via the `profile` property which auto-fetches if needed.

    Example:
        >>> member = client.members.get("member-id")
        >>> member.profile.dietary_groups = ["vegan"]
    """

    def __init__(
        self,
        client: Optional["Client"] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        self._client = client
        self._data = data or {}
        self._profile: Optional[HouseholdMemberProfile] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], client: Optional["Client"] = None) -> "HouseholdMember":
        return cls(client=client, data=data)

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def name(self) -> str:
        return self._data.get("name", "")

    @name.setter
    def name(self, value: str) -> None:
        self._data["name"] = value
        self._sync_field("name", value)

    @property
    def age_group(self) -> str:
        return self._data.get("age_group", "")

    @age_group.setter
    def age_group(self, value: str) -> None:
        self._data["age_group"] = value
        self._sync_field("age_group", value)

    @property
    def household_id(self) -> str:
        return self._data.get("household_id", "")

    @property
    def image_url(self) -> Optional[str]:
        return self._data.get("image_url")

    @image_url.setter
    def image_url(self, value: Optional[str]) -> None:
        self._data["image_url"] = value
        self._sync_field("image_url", value)

    @property
    def created_at(self) -> Optional[str]:
        return self._data.get("created_at")

    @property
    def updated_at(self) -> Optional[str]:
        return self._data.get("updated_at")

    @property
    def profile(self) -> HouseholdMemberProfile:
        """
        Get the member's profile, fetching from API if not loaded.

        Returns a profile object where setting properties auto-syncs to API.

        Example:
            >>> member.profile.dietary_groups = ["vegetarian"]
            >>> member.profile.nutritional_preferences = {"protein": 50}
        """
        if self._profile is None:
            if not self._client:
                raise RuntimeError("Member not bound to a client")
            try:
                resp = self._client.get(f"members/{self.id}/profile")
                data = resp.json().get("result", resp.json())
            except Exception:
                # Profile might not exist yet, return empty profile
                data = {}
            self._profile = HouseholdMemberProfile(
                client=self._client,
                member_id=self.id,
                data=data,
            )
        return self._profile

    def _sync_field(self, field: str, value: Any) -> None:
        """Sync a single field to the API."""
        if self._client:
            self._client.patch(f"members/{self.id}", json={field: value})

    def refresh(self) -> None:
        """Reload member data from the API."""
        if not self._client:
            raise RuntimeError("Member not bound to a client")
        resp = self._client.get(f"members/{self.id}")
        self._data = resp.json().get("result", resp.json())
        self._profile = None  # Reset profile to force re-fetch

    def delete(self) -> None:
        """Delete this member."""
        if not self._client:
            raise RuntimeError("Member not bound to a client")
        self._client.delete(f"members/{self.id}")

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"<HouseholdMember id='{self.id}' name='{self.name}'>"


class Household:
    """
    A household in the WiseFood system.

    Example:
        >>> household = client.households.me()
        >>> household.name = "New Family Name"  # auto-syncs
        >>> members = household.members
    """

    def __init__(
        self,
        client: Optional["Client"] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        self._client = client
        self._data = data or {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any], client: Optional["Client"] = None) -> "Household":
        return cls(client=client, data=data)

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def name(self) -> str:
        return self._data.get("name", "")

    @name.setter
    def name(self, value: str) -> None:
        self._data["name"] = value
        self._sync_field("name", value)

    @property
    def owner_id(self) -> str:
        return self._data.get("owner_id", "")

    @property
    def region(self) -> Optional[str]:
        return self._data.get("region")

    @region.setter
    def region(self, value: Optional[str]) -> None:
        self._data["region"] = value
        self._sync_field("region", value)

    @property
    def metadata(self) -> Optional[Dict[str, Any]]:
        return self._data.get("metadata")

    @metadata.setter
    def metadata(self, value: Optional[Dict[str, Any]]) -> None:
        self._data["metadata"] = value
        self._sync_field("metadata", value)

    @property
    def created_at(self) -> Optional[str]:
        return self._data.get("created_at")

    @property
    def updated_at(self) -> Optional[str]:
        return self._data.get("updated_at")

    @property
    def members(self) -> List["HouseholdMember"]:
        """Get all members of this household."""
        if not self._client:
            raise RuntimeError("Household not bound to a client")
        resp = self._client.get(f"households/{self.id}/members")
        data = resp.json().get("result", resp.json())
        if isinstance(data, list):
            return [HouseholdMember.from_dict(m, self._client) for m in data]
        return []

    def _sync_field(self, field: str, value: Any) -> None:
        """Sync a single field to the API."""
        if self._client:
            self._client.patch(f"households/{self.id}", json={field: value})

    def add_member(self, name: str, age_group: str, **kwargs) -> "HouseholdMember":
        """Add a new member to this household."""
        if not self._client:
            raise RuntimeError("Household not bound to a client")
        payload = {"name": name, "age_group": age_group, "household_id": self.id, **kwargs}
        resp = self._client.post("members", json=payload)
        data = resp.json().get("result", resp.json())
        return HouseholdMember.from_dict(data, self._client)

    def refresh(self) -> None:
        """Reload household data from the API."""
        if not self._client:
            raise RuntimeError("Household not bound to a client")
        resp = self._client.get(f"households/{self.id}")
        self._data = resp.json().get("result", resp.json())

    def delete(self) -> None:
        """Delete this household."""
        if not self._client:
            raise RuntimeError("Household not bound to a client")
        self._client.delete(f"households/{self.id}")

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"<Household id='{self.id}' name='{self.name}'>"


# ---------------------------------------------------------------------------
# Proxy Classes
# ---------------------------------------------------------------------------


class HouseholdsProxy:
    """
    Proxy for household operations.

    Provides convenient access to household CRUD operations through the Client.

    Example:
        >>> client.households.me()  # Get current user's household
        >>> client.households.get("household-id-123")
        >>> client.households.create(name="My Family")
    """

    def __init__(self, client: "Client") -> None:
        self._client = client

    def me(self) -> Household:
        """
        Get the household owned by the authenticated user.

        Returns:
            Household object for the current user

        Example:
            >>> household = client.households.me()
            >>> print(household.name)
        """
        resp = self._client.get("households/me")
        data = resp.json().get("result", resp.json())
        return Household.from_dict(data, self._client)

    def get(self, household_id: str) -> Household:
        """
        Get a household by ID.

        Args:
            household_id: The household's unique identifier

        Returns:
            Household object

        Example:
            >>> household = client.households.get("abc123")
        """
        resp = self._client.get(f"households/{household_id}")
        data = resp.json().get("result", resp.json())
        return Household.from_dict(data, self._client)

    def list(self, limit: int = 100, offset: int = 0) -> List[Household]:
        """
        List all households (admin only).

        Args:
            limit: Maximum number of results (default: 100)
            offset: Number of results to skip (default: 0)

        Returns:
            List of Household objects

        Example:
            >>> households = client.households.list(limit=50)
        """
        resp = self._client.get("households", limit=limit, offset=offset)
        data = resp.json().get("result", resp.json())
        if isinstance(data, list):
            return [Household.from_dict(h, self._client) for h in data]
        return []

    def create(self, name: str, region: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None,
               members: Optional[List[Dict[str, Any]]] = None) -> Household:
        """
        Create a new household.

        Args:
            name: Household name
            region: Optional region identifier
            metadata: Optional metadata dictionary
            members: Optional list of initial members to create

        Returns:
            Created Household object

        Example:
            >>> household = client.households.create(
            ...     name="My Family",
            ...     region="US-CA",
            ...     members=[{"name": "John", "age_group": "adult"}]
            ... )
        """
        payload: Dict[str, Any] = {"name": name}
        if region:
            payload["region"] = region
        if metadata:
            payload["metadata"] = metadata
        if members:
            payload["members"] = members
        resp = self._client.post("households", json=payload)
        data = resp.json().get("result", resp.json())
        return Household.from_dict(data, self._client)

    def update(self, household_id: str, **kwargs) -> Household:
        """
        Update a household.

        Args:
            household_id: The household's unique identifier
            **kwargs: Fields to update (name, region, metadata)

        Returns:
            Updated Household object

        Example:
            >>> household = client.households.update("abc123", name="New Name")
        """
        resp = self._client.patch(f"households/{household_id}", json=kwargs)
        data = resp.json().get("result", resp.json())
        return Household.from_dict(data, self._client)

    def delete(self, household_id: str) -> None:
        """
        Delete a household.

        Args:
            household_id: The household's unique identifier

        Example:
            >>> client.households.delete("abc123")
        """
        self._client.delete(f"households/{household_id}")


class MembersProxy:
    """
    Proxy for household member operations.

    Provides convenient access to member CRUD operations through the Client.

    Example:
        >>> member = client.members.get("member-id-123")
        >>> member.profile.dietary_groups = ["vegetarian"]  # auto-syncs
    """

    def __init__(self, client: "Client") -> None:
        self._client = client

    def get(self, member_id: str) -> HouseholdMember:
        """
        Get a household member by ID.

        Args:
            member_id: The member's unique identifier

        Returns:
            HouseholdMember object with auto-syncing profile

        Example:
            >>> member = client.members.get("member123")
            >>> member.profile.dietary_groups = ["vegan"]
        """
        resp = self._client.get(f"members/{member_id}")
        data = resp.json().get("result", resp.json())
        return HouseholdMember.from_dict(data, self._client)

    def list(self, household_id: str, limit: int = 100, offset: int = 0) -> List[HouseholdMember]:
        """
        List household members.

        Args:
            household_id: The household's unique identifier
            limit: Maximum number of results (default: 100)
            offset: Number of results to skip (default: 0)

        Returns:
            List of HouseholdMember objects

        Example:
            >>> members = client.members.list(household_id="abc123")
        """
        resp = self._client.get("members", household_id=household_id, limit=limit, offset=offset)
        data = resp.json().get("result", resp.json())
        if isinstance(data, list):
            return [HouseholdMember.from_dict(m, self._client) for m in data]
        return []

    def create(self, household_id: str, name: str, age_group: str,
               image_url: Optional[str] = None) -> HouseholdMember:
        """
        Create a new household member.

        Args:
            household_id: The household's unique identifier
            name: Member name
            age_group: Age group (child, teen, adult, senior, etc.)
            image_url: Optional URL to member's profile image

        Returns:
            Created HouseholdMember object

        Example:
            >>> member = client.members.create(
            ...     household_id="abc123",
            ...     name="John",
            ...     age_group="adult"
            ... )
            >>> member.profile.dietary_groups = ["vegetarian"]
        """
        payload: Dict[str, Any] = {
            "household_id": household_id,
            "name": name,
            "age_group": age_group,
        }
        if image_url:
            payload["image_url"] = image_url
        resp = self._client.post("members", json=payload)
        data = resp.json().get("result", resp.json())
        return HouseholdMember.from_dict(data, self._client)

    def delete(self, member_id: str) -> None:
        """
        Delete a household member.

        Args:
            member_id: The member's unique identifier

        Example:
            >>> client.members.delete("member123")
        """
        self._client.delete(f"members/{member_id}")
