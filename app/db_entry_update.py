from typing import Optional, Set, Dict, Any, Tuple
from datetime import datetime
from asyncio import sleep

from urllib.parse import urlparse
from malexport.parse.common import parse_date_safe
from sqlalchemy import update
from sqlmodel import Session
from sqlmodel.sql.expression import select
from url_cache.core import Summary

from mal_id.metadata_cache import request_metadata
from mal_id.linear_history import read_linear_history, Entry
from mal_id.ids import approved_ids, unapproved_ids
from mal_id.paths import metadatacache_dir
from mal_id.log import logger

from app.db import (
    Status,
    AnimeMetadata,
    MangaMetadata,
    data_engine,
    ProxiedImage,
    EntryType,
)
from app.image_proxy import proxy_image


def api_url_to_parts(url: str) -> tuple[str, int]:
    uu = urlparse(url)
    assert uu.path.startswith("/v2")
    is_anime = uu.path.startswith("/v2/anime")
    entry_type = "anime" if is_anime else "manga"
    url_id = uu.path.split("/")[3]
    return entry_type, int(url_id)


def test_api_url_to_parts() -> None:
    assert api_url_to_parts(
        "https://api.myanimelist.net/v2/manga/113372?nsfw=true&fields=id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,rank,popularity,num_list_users,num_scoring_users,nsfw,created_at,updated_at,media_type,status,genres,num_volumes,num_chapters,authors{first_name,last_name},pictures,background,related_anime,related_manga,recommendations,serialization{name}"
    ) == ("manga", 113372)

    assert api_url_to_parts(
        "https://api.myanimelist.net/v2/anime/48420?nsfw=true&fields=id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,rank,popularity,num_list_users,num_scoring_users,nsfw,created_at,updated_at,media_type,status,genres,num_episodes,start_season,broadcast,source,average_episode_duration,rating,pictures,background,related_anime,related_manga,recommendations,studios,statistics"
    ) == ("anime", 48420)


# ???
# who even knows what gray nsfw means??
# some that have hentai in manga are marked grey, others arent?
def is_nsfw(jdata: Dict[str, Any]) -> Optional[bool]:
    if "rating" in jdata:
        return bool(jdata["rating"] == "rx")
    else:
        if "genres" in jdata:
            return bool("Hentai" in (g["name"] for g in jdata["genres"]))
    return None


def _get_img_url(data: dict) -> str | None:
    if img := data.get("medium"):
        assert isinstance(img, str)
        return img
    if img := data.get("large"):
        assert isinstance(img, str)
        return img
    return None


def summary_main_image(summary: Summary) -> str | None:
    if pictures := summary.metadata.get("main_picture"):
        if img := _get_img_url(pictures):
            return img
    return None


def summary_proxy_image(summary: Summary) -> str | None:
    if main_image := summary_main_image(summary):
        return proxy_image(main_image)
    return None


def add_or_update(
    *,
    summary: Summary,
    current_approved_status: Status | None = None,
    old_status: Optional[Status] = None,
    in_db: Optional[Set[int]] = None,
    added_dt: Optional[datetime] = None,
    force_update: bool = False,
    mal_id_to_image: Optional[Dict[Tuple[EntryType, int], str]] = None,
    refresh_images: bool = False,
    skip_images: bool = False,
) -> None:
    entry_type, url_id = api_url_to_parts(summary.url)
    entry_enum = EntryType.from_str(entry_type)
    assert entry_type in ("anime", "manga")

    jdata = dict(summary.metadata)
    if "error" in jdata:
        logger.debug(f"skipping http error in {entry_type} {url_id}: {jdata['error']}")
        return

    if skip_images is False:
        img = summary_proxy_image(summary)
        # may be that the summary is so old a new image has been added instead
        if img is None and refresh_images is True:
            summary = request_metadata(url_id, entry_type, force_rerequest=True)
            img = summary_proxy_image(summary)
            if img is not None:
                logger.info(
                    f"db: {entry_type} {url_id} successfully refreshed image {img}"
                )

        # if force refreshing an entry, select the single image row from the db
        if mal_id_to_image is None:
            logger.debug(f"db: {entry_type} {url_id} fetching image row from db")
            with Session(data_engine) as sess:
                mal_id_to_image = {
                    (i.mal_entry_type, i.mal_id): i.proxied_url
                    for i in sess.exec(
                        select(ProxiedImage)
                        .where(ProxiedImage.mal_id == url_id)
                        .where(ProxiedImage.mal_entry_type == entry_enum)
                    ).all()
                }

        # if we have the local dict db and we have a proxied image
        if mal_id_to_image is not None and img is not None:
            mal_image_url = summary_main_image(summary)

            image_key = (entry_enum, url_id)

            if mal_image_url is not None:
                # if this isnt already in the database
                if image_key not in mal_id_to_image:
                    with Session(data_engine) as sess:
                        sess.add(
                            ProxiedImage(
                                mal_entry_type=entry_enum,
                                mal_id=url_id,
                                mal_url=mal_image_url,
                                proxied_url=img,
                            )
                        )
                        sess.commit()
                else:
                    # if we have the image in the database and it is different
                    if mal_id_to_image[image_key] != img:
                        with Session(data_engine) as sess:
                            sess.exec(
                                update(ProxiedImage)  # type: ignore
                                .where(ProxiedImage.mal_entry_type == entry_enum)
                                .where(ProxiedImage.mal_id == url_id)
                                .values(mal_url=mal_image_url, proxied_url=img)
                            )
                            sess.commit()

    use_model = AnimeMetadata if entry_type == "anime" else MangaMetadata

    # pop data from the json that get stored in the db
    aid = int(jdata.pop("id"))
    title = jdata.pop("title")
    start_date = parse_date_safe(jdata.pop("start_date", None))
    end_date = parse_date_safe(jdata.pop("end_date", None))

    # try to figure out if this is sfw/nsfw
    nsfw = is_nsfw(jdata)

    # figure out if entry is the in db
    # if force rerequesting, dont have access to in_db/statuses
    entry_in_db = False
    if in_db is not None:
        entry_in_db = aid in in_db
    else:
        with Session(data_engine) as sess:
            assert hasattr(use_model, "id")
            entry_req = sess.exec(select(use_model).where(use_model.id == aid)).first()
            entry_in_db = entry_req is not None

    if entry_in_db:
        # update the entry if the status has changed or if this didnt exist in the db
        if force_update or (
            (
                current_approved_status is not None
                and current_approved_status != old_status
            )
            or old_status is None
        ):
            if force_update:
                logger.debug(f"db: {entry_type} {aid} force updating")
            else:
                logger.info(f"updating data for {entry_type} {aid} (status changed)")
            kwargs = {}
            if current_approved_status is not None:
                kwargs["approved_status"] = current_approved_status
            # update the status to deleted
            stmt = (
                update(use_model)
                .where(use_model.id == aid)  # type: ignore[attr-defined]
                .values(
                    title=title,
                    start_date=start_date,
                    end_date=end_date,
                    json_data=jdata,
                    updated_at=summary.timestamp,
                    nsfw=nsfw,
                    **kwargs,
                )
            )
            with Session(data_engine) as sess:
                sess.exec(stmt)  # type: ignore[call-overload]
                sess.commit()
    else:
        if current_approved_status is None:
            logger.warning(
                f"trying to add {entry_type} {aid} with status as None! skipping..."
            )
            return
        logger.info(f"adding {entry_type} {aid} to db")
        # add the entry
        with Session(data_engine) as sess:
            sess.add(
                use_model(
                    approved_status=current_approved_status,
                    approved_at=added_dt,
                    id=aid,
                    title=title,
                    start_date=start_date,
                    end_date=end_date,
                    updated_at=summary.timestamp,
                    json_data=jdata,
                    nsfw=nsfw,
                )
            )
            sess.commit()


async def status_map() -> Dict[str, Any]:
    with Session(data_engine) as sess:
        in_db: Dict[str, Any] = {
            "anime_tup": set(
                sess.query(AnimeMetadata.id, AnimeMetadata.approved_status)
            ),
            "manga_tup": set(
                sess.query(MangaMetadata.id, MangaMetadata.approved_status)
            ),
        }
    in_db["anime"] = set(i for i, _ in in_db["anime_tup"])
    in_db["manga"] = set(i for i, _ in in_db["manga_tup"])

    in_db["anime_status"] = {i: s for i, s in in_db["anime_tup"]}
    in_db["manga_status"] = {i: s for i, s in in_db["manga_tup"]}

    return in_db


def malid_to_image() -> Dict[Tuple[EntryType, int], str]:
    with Session(data_engine) as sess:
        return {
            (i.mal_entry_type, i.mal_id): i.proxied_url
            for i in sess.exec(select(ProxiedImage)).all()
        }


async def update_database(
    refresh_images: bool = False,
    force_update_db: bool = False,
    skip_proxy_images: bool = False,
) -> None:
    #  make sure MAL API is up

    from mal_id.metadata_cache import check_mal

    if not check_mal():
        logger.warning("mal api is down, skipping db update")
        return

    logger.info("Updating database...")

    known: Set[str] = set()
    in_db = await status_map()

    mal_id_image_have = malid_to_image()

    approved = approved_ids()
    logger.info("db: reading from linear history...")
    for i, hdict in enumerate(read_linear_history()):
        hval = Entry.from_dict(hdict)

        # be nice to other tasks
        if i % 10 == 0:
            await sleep(0)
        approved_use: Set[int] = getattr(approved, hval.e_type)

        # if its in the linear history, it was approved at one point
        # but it may not be anymore
        current_id_status = (
            Status.APPROVED if hval.entry_id in approved_use else Status.DELETED
        )

        old_status = in_db[f"{hval.e_type}_status"].get(hval.entry_id)
        was_approved = False
        if current_id_status == Status.APPROVED and old_status == Status.UNAPPROVED:
            logger.info(
                f"updating {hval.e_type} {hval.entry_id} to approved (was unapproved), rerequesting data"
            )
            was_approved = True

        add_or_update(
            summary=request_metadata(
                hval.entry_id, hval.e_type, force_rerequest=was_approved
            ),
            current_approved_status=current_id_status,
            old_status=old_status,
            in_db=in_db[hval.e_type],
            added_dt=hval.dt,
            refresh_images=refresh_images,
            force_update=force_update_db,
            skip_images=skip_proxy_images,
            mal_id_to_image=mal_id_image_have,
        )
        known.add(hval.key)

    unapproved = unapproved_ids()
    logger.info("db: updating from unapproved anime history...")
    for i, aid in enumerate(unapproved.anime):
        if i % 10 == 0:
            await sleep(0)
        add_or_update(
            summary=request_metadata(aid, "anime"),
            old_status=in_db["anime_status"].get(aid),
            current_approved_status=Status.UNAPPROVED,
            in_db=in_db["anime"],
            refresh_images=refresh_images,
            force_update=force_update_db,
            skip_images=skip_proxy_images,
            mal_id_to_image=mal_id_image_have,
        )
        known.add(f"anime_{aid}")

    logger.info("db: updating from unapproved manga history...")
    for i, mid in enumerate(unapproved.manga):
        if i % 10 == 0:
            await sleep(0)
        add_or_update(
            summary=request_metadata(mid, "manga"),
            old_status=in_db["manga_status"].get(mid),
            current_approved_status=Status.UNAPPROVED,
            in_db=in_db["manga"],
            refresh_images=refresh_images,
            force_update=force_update_db,
            skip_images=skip_proxy_images,
            mal_id_to_image=mal_id_image_have,
        )
        known.add(f"manga_{mid}")

    logger.info("db: checking for deleted entries...")
    # check if any other items exist that arent in the db already
    # those were denied or deleted (long time ago)
    all_keys = [p.absolute() for p in metadatacache_dir.rglob("*/key")]
    all_urls = set(p.read_text() for p in all_keys)
    for i, (entry_type, entry_id) in enumerate(map(api_url_to_parts, all_urls)):
        if i % 10 == 0:
            await sleep(0)
        key = f"{entry_type}_{entry_id}"
        if key not in known:
            add_or_update(
                summary=request_metadata(entry_id, entry_type),
                current_approved_status=Status.DENIED,
                refresh_images=refresh_images,
                force_update=force_update_db,
                skip_images=skip_proxy_images,
                mal_id_to_image=mal_id_image_have,
            )
            known.add(key)

    logger.info("db: done with full update")


async def refresh_entry(*, entry_id: int, entry_type: str) -> None:
    summary = request_metadata(entry_id, entry_type, force_rerequest=True)
    await sleep(0)
    logger.info(f"db: refreshed data for {entry_type} {entry_id}")
    add_or_update(
        summary=summary,
        force_update=True,
    )
