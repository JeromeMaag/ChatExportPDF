from __future__ import annotations
import sqlite3
from typing import Dict, List

from ..models import Contact, Conversation, GroupInfo, Message
from ..util import bytes_to_hex
from .schema import row_get, table_columns

def load_contacts(conn: sqlite3.Connection) -> Dict[int, Contact]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          Z_PK, ZIDENTITY, ZFIRSTNAME, ZLASTNAME, ZPROPERTY1 AS nick, ZPUBLICNICKNAME,
          ZCNCONTACTID, ZCSI, ZDEPARTMENT, ZJOBTITLE, ZVERIFIEDEMAIL, ZVERIFIEDMOBILENO,
          ZCREATEDAT, ZPROFILEPICTUREUPLOAD,
          ZVERIFICATIONLEVEL, ZSTATE, ZHIDDEN, ZWORKCONTACT,
          ZFEATUREMASK, ZFORWARDSECURITYSTATE, ZREADRECEIPTS, ZTYPINGINDICATORS,
          ZIMPORTSTATUS, ZPROFILEPICTURESENDED, ZSORTINDEX,
          ZPROFILEPICTUREBLOBID, ZPUBLICKEY
        FROM ZCONTACT;
        """
    )
    out: Dict[int, Contact] = {}
    for r in cur.fetchall():
        out[int(r["Z_PK"])] = Contact(
            pk=int(r["Z_PK"]),
            identity=r["ZIDENTITY"],
            first=r["ZFIRSTNAME"],
            last=r["ZLASTNAME"],
            nick=r["nick"],
            public_nick=r["ZPUBLICNICKNAME"],
            cncontactid=r["ZCNCONTACTID"],
            csi=r["ZCSI"],
            department=r["ZDEPARTMENT"],
            jobtitle=r["ZJOBTITLE"],
            verifiedemail=r["ZVERIFIEDEMAIL"],
            verifiedmobileno=r["ZVERIFIEDMOBILENO"],
            createdat_raw=r["ZCREATEDAT"],
            profilepictureupload_raw=r["ZPROFILEPICTUREUPLOAD"],
            verificationlevel=r["ZVERIFICATIONLEVEL"],
            state=r["ZSTATE"],
            hidden=r["ZHIDDEN"],
            workcontact=r["ZWORKCONTACT"],
            featuremask=r["ZFEATUREMASK"],
            forwardsecuritystate=r["ZFORWARDSECURITYSTATE"],
            readreceipts=r["ZREADRECEIPTS"],
            typingindicators=r["ZTYPINGINDICATORS"],
            importstatus=r["ZIMPORTSTATUS"],
            profilepicturesended=r["ZPROFILEPICTURESENDED"],
            sortindex=r["ZSORTINDEX"],
            profilepictureblobid=r["ZPROFILEPICTUREBLOBID"],
            publickey=r["ZPUBLICKEY"],
        )
    return out

def load_groups(conn: sqlite3.Connection) -> Dict[str, GroupInfo]:
    cur = conn.cursor()
    cur.execute("SELECT Z_PK, ZGROUPID, ZGROUPCREATOR, ZSTATE, ZLASTPERIODICSYNC FROM ZGROUP;")
    out: Dict[str, GroupInfo] = {}
    for r in cur.fetchall():
        gid_hex = bytes_to_hex(r["ZGROUPID"])
        if gid_hex:
            out[gid_hex] = GroupInfo(
                pk=int(r["Z_PK"]),
                group_id_hex=gid_hex,
                creator=r["ZGROUPCREATOR"],
                state=r["ZSTATE"],
                last_periodic_sync_raw=r["ZLASTPERIODICSYNC"],
            )
    return out

def load_conversations(conn: sqlite3.Connection) -> List[Conversation]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT Z_PK, ZCATEGORY, ZMARKED, ZUNREADMESSAGECOUNT, ZVISIBILITY,
               ZCONTACT, ZGROUPNAME, ZGROUPID, ZGROUPMYIDENTITY, ZLASTUPDATE
        FROM ZCONVERSATION
        ORDER BY Z_PK;
        """
    )
    out: List[Conversation] = []
    for r in cur.fetchall():
        out.append(
            Conversation(
                pk=int(r["Z_PK"]),
                category=r["ZCATEGORY"],
                contact_pk=r["ZCONTACT"],
                group_name=r["ZGROUPNAME"],
                group_id_hex=bytes_to_hex(r["ZGROUPID"]),
                group_my_identity=r["ZGROUPMYIDENTITY"],
                unread_count=r["ZUNREADMESSAGECOUNT"],
                last_update_raw=r["ZLASTUPDATE"],
                visibility=r["ZVISIBILITY"],
                marked=r["ZMARKED"],
            )
        )
    return out

def load_group_members(conn: sqlite3.Connection) -> Dict[int, List[int]]:
    cur = conn.cursor()
    m: Dict[int, List[int]] = {}
    cur.execute("SELECT Z_6MEMBERS, Z_7GROUPCONVERSATIONS FROM Z_6GROUPCONVERSATIONS;")
    for r in cur.fetchall():
        conv_pk = int(r["Z_7GROUPCONVERSATIONS"])
        contact_pk = int(r["Z_6MEMBERS"])
        m.setdefault(conv_pk, []).append(contact_pk)
    return m

def load_messages_for_conversation(conn: sqlite3.Connection, conv_pk: int) -> List[Message]:
    cols = table_columns(conn, "ZMESSAGE")
    wanted = [
        "Z_PK","Z_ENT","ZCONVERSATION","ZSENDER","ZISOWN",
        "ZDATE","ZDELIVERED","ZREAD","ZSENT","ZSENDFAILED","ZUSERACK",
        "ZDELIVERYDATE","ZREADDATE","ZREMOTESENTDATE","ZLASTEDITEDAT","ZDELETEDAT",
        "ZTEXT","ZCAPTION","ZFILENAME","ZMIMETYPE","ZJSON",
        "ZID","ZQUOTEDMESSAGEID",
        "ZBLOBID","ZBLOBTHUMBNAILID","ZIMAGEBLOBID","ZAUDIOBLOBID","ZVIDEOBLOBID",
        "ZENCRYPTIONKEY","ZENCRYPTIONKEY1","ZENCRYPTIONKEY2","ZENCRYPTIONKEY3",
        "ZIMAGENONCE","ZARG",
        "ZIMAGE","ZAUDIO","ZVIDEO","ZDATA",
        "ZTYPE","ZFLAGS","ZORIGIN",
    ]
    select_cols = [c for c in wanted if c in cols]
    sql = f"""
        SELECT {", ".join(select_cols)}
        FROM ZMESSAGE
        WHERE ZCONVERSATION = ?
        ORDER BY ZDATE ASC, Z_PK ASC;
    """
    cur = conn.cursor()
    cur.execute(sql, (conv_pk,))
    out: List[Message] = []
    for r in cur.fetchall():
        out.append(
            Message(
                pk=int(row_get(r,"Z_PK")),
                ent=int(row_get(r,"Z_ENT")),
                conversation_pk=int(row_get(r,"ZCONVERSATION")),
                sender_pk=row_get(r,"ZSENDER"),
                is_own=row_get(r,"ZISOWN"),
                date_raw=row_get(r,"ZDATE"),
                delivered=row_get(r,"ZDELIVERED"),
                read=row_get(r,"ZREAD"),
                sent=row_get(r,"ZSENT"),
                sendfailed=row_get(r,"ZSENDFAILED"),
                userack=row_get(r,"ZUSERACK"),
                deliverydate_raw=row_get(r,"ZDELIVERYDATE"),
                readdate_raw=row_get(r,"ZREADDATE"),
                remotesentdate_raw=row_get(r,"ZREMOTESENTDATE"),
                lasteditedat_raw=row_get(r,"ZLASTEDITEDAT"),
                deletedat_raw=row_get(r,"ZDELETEDAT"),
                text=row_get(r,"ZTEXT"),
                caption=row_get(r,"ZCAPTION"),
                filename=row_get(r,"ZFILENAME"),
                mimetype=row_get(r,"ZMIMETYPE"),
                json=row_get(r,"ZJSON"),
                zid=row_get(r,"ZID"),
                quoted_message_id=row_get(r,"ZQUOTEDMESSAGEID"),
                blobid=row_get(r,"ZBLOBID"),
                blobthumbid=row_get(r,"ZBLOBTHUMBNAILID"),
                imageblobid=row_get(r,"ZIMAGEBLOBID"),
                audioblobid=row_get(r,"ZAUDIOBLOBID"),
                videoblobid=row_get(r,"ZVIDEOBLOBID"),
                encryptionkey=row_get(r,"ZENCRYPTIONKEY"),
                encryptionkey1=row_get(r,"ZENCRYPTIONKEY1"),
                encryptionkey2=row_get(r,"ZENCRYPTIONKEY2"),
                encryptionkey3=row_get(r,"ZENCRYPTIONKEY3"),
                imagenonce=row_get(r,"ZIMAGENONCE"),
                arg=row_get(r,"ZARG"),
                zimage_fk=row_get(r,"ZIMAGE"),
                zaudio_fk=row_get(r,"ZAUDIO"),
                zvideo_fk=row_get(r,"ZVIDEO"),
                zdata_fk=row_get(r,"ZDATA"),
                ztype=row_get(r,"ZTYPE"),
                zflags=row_get(r,"ZFLAGS"),
                zorigin=row_get(r,"ZORIGIN"),
            )
        )
    return out

def load_reactions(conn: sqlite3.Connection, msg_pk: int) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ZCREATOR, ZDATE, ZREACTION
        FROM ZMESSAGEREACTION
        WHERE ZMESSAGE = ? OR Z14_MESSAGE = ?
        ORDER BY ZDATE ASC;
        """,
        (msg_pk, msg_pk),
    )
    return cur.fetchall()

def load_history(conn: sqlite3.Connection, msg_pk: int) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ZEDITDATE, ZTEXT
        FROM ZMESSAGEHISTORYENTRY
        WHERE ZMESSAGE = ? OR Z14_MESSAGE = ?
        ORDER BY ZEDITDATE ASC;
        """,
        (msg_pk, msg_pk),
    )
    return cur.fetchall()
