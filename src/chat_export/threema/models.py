"""Define importer-side Threema data models.

This module contains source-specific dataclasses used by the Threema importer.
They map closely to the SQLite schema and are later converted to normalized
conversation models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

ENT_MAP = {
    15: "Audio",
    16: "Ballot",
    17: "File",
    18: "Image",
    19: "Location",
    20: "System",
    21: "Text",
    22: "Video",
}


@dataclass
class Contact:
    """Store one Threema contact row."""

    pk: int
    identity: Optional[str]
    first: Optional[str]
    last: Optional[str]
    nick: Optional[str]
    public_nick: Optional[str]

    cncontactid: Optional[str]
    csi: Optional[str]
    department: Optional[str]
    jobtitle: Optional[str]
    verifiedemail: Optional[str]
    verifiedmobileno: Optional[str]

    createdat_raw: Any
    profilepictureupload_raw: Any

    verificationlevel: Optional[int]
    state: Optional[int]
    hidden: Optional[int]
    workcontact: Optional[int]

    featuremask: Optional[int]
    forwardsecuritystate: Optional[int]
    readreceipts: Optional[int]
    typingindicators: Optional[int]

    importstatus: Optional[int]
    profilepicturesended: Optional[int]
    sortindex: Optional[int]

    profilepictureblobid: Optional[str]
    publickey: Optional[bytes]

    def display_name(self) -> str:
        """Resolve the preferred display name for one contact.

        Returns:
            str: Public nick, full name, nickname, identity, or fallback label.
        """
        if self.public_nick and self.public_nick.strip():
            return self.public_nick.strip()
        name = " ".join(
            [x.strip() for x in [self.first or "", self.last or ""] if x and x.strip()]
        )
        if name:
            return name
        if self.nick and self.nick.strip():
            return self.nick.strip()
        if self.identity and self.identity.strip():
            return self.identity.strip()
        return f"Contact#{self.pk}"


@dataclass
class Conversation:
    """Store one Threema conversation row."""

    pk: int
    category: Optional[int]
    contact_pk: Optional[int]
    group_name: Optional[str]
    group_id_hex: Optional[str]
    group_my_identity: Optional[str]
    unread_count: Optional[int]
    last_update_raw: Any
    visibility: Optional[int]
    marked: Optional[int]


@dataclass
class GroupInfo:
    """Store one Threema group metadata row."""

    pk: int
    group_id_hex: Optional[str]
    creator: Optional[str]
    state: Optional[int]
    last_periodic_sync_raw: Any


@dataclass
class Message:
    """Store one Threema message row."""

    pk: int
    ent: int
    conversation_pk: int
    sender_pk: Optional[int]
    is_own: Optional[int]
    date_raw: Any

    delivered: Optional[int]
    read: Optional[int]
    sent: Optional[int]
    sendfailed: Optional[int]
    userack: Optional[int]

    deliverydate_raw: Any
    readdate_raw: Any
    remotesentdate_raw: Any
    lasteditedat_raw: Any
    deletedat_raw: Any

    text: Optional[str]
    caption: Optional[str]
    filename: Optional[str]
    mimetype: Optional[str]
    json: Optional[str]

    zid: Optional[bytes]
    quoted_message_id: Optional[bytes]

    blobid: Optional[bytes]
    blobthumbid: Optional[bytes]
    imageblobid: Optional[bytes]
    audioblobid: Optional[bytes]
    videoblobid: Optional[bytes]

    encryptionkey: Optional[bytes]
    encryptionkey1: Optional[bytes]
    encryptionkey2: Optional[bytes]
    encryptionkey3: Optional[bytes]
    imagenonce: Optional[bytes]
    arg: Optional[bytes]

    zimage_fk: Optional[int]
    zaudio_fk: Optional[int]
    zvideo_fk: Optional[int]
    zdata_fk: Optional[int]

    ztype: Optional[int]
    zflags: Optional[int]
    zorigin: Optional[int]
