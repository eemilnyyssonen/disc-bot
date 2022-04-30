# -*- coding: utf-8 -*-
"""
Created on Fri Apr  2 22:39:23 2021

@author: Eemil 

Runs and initializes the app
"""
import os
import logging
import requests
import imgkit
import pandas as pd
from dotenv import load_dotenv
from telegram import Update, ForceReply
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)
from scrape import Scrape, OnState



# Get envs from .env
load_dotenv(verbose=True)
# Get envs needed
BOT_TOKEN = os.getenv("TOKEN")
URL = os.getenv("URL")
CHAT_ID = os.getenv("CHAT_ID")
# Targets, init targets from bot
TARGETS = []

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def start(update: Update, _: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    update.message.reply_markdown_v2(
        f"Hi {user.mention_markdown_v2()}\!",
        reply_markup=ForceReply(selective=True),
    )

 
def add_targets(update: Update, context: CallbackContext) -> None:
    """Add items to the target list."""
    try:
        new_targets = context.args
        if not new_targets:
            update.message.reply_text(
                "No targets to add! Try for example: </init Shryke Pig>"
            )
            return
        sess.add_targets(new_targets)
        update.message.reply_text(
            "Added the following targets to the list:\n" + ", ".join(new_targets)
        )
    except Exception as e:
        logger.warning(f"Function add_targets raised an exception: {e}")
        update.message.reply_text("Usage: /add <target1 target2 target3 ... >")


def targets(update: Update, _: CallbackContext) -> None:
    update.message.reply_text(
        "The current targets are defined as: "
        + ", ".join(target.lower() for target in TARGETS)
        + ".\nIf you wish to modify the targets try command: /modify_targets."
    )


def on_alarm(context: CallbackContext) -> None:
    """Update product when said time is elapsed"""
    logger.info("Timer done!")
    job = context.job
    sess.update_search()
    t = (
        "Update done at: "
        + sess.get_current_time()
        + "!\n"
        + sess.get_results().to_string()
    )
    context.bot.send_message(job.context, text=t)


def init_targets(update: Update, context: CallbackContext) -> None:
    """Init the target list."""
    try:
        new_targets = context.args
        if not new_targets:
            update.message.reply_text(
                "No targets to add! Try for example: </init Shryke Pig>"
            )
            return
        sess.mod_targets(new_targets)
        update.message.reply_text(
            "Initialized the target list with the following targets:\n" + ", ".join(new_targets)
        )
    except Exception as e:
        logger.warning(f"Function init_targets raised an exception: {e}")
        update.message.reply_text("Usage: /init <target1 target2 target3 ... >")


def updates(update: Update, _: CallbackContext) -> None:
    """Update the scraping session."""
    sess.update_search()
    if sess.get_state():
        results = sess.get_results()
        [update.message.reply_markdown_v2( "```"
                                        + results.iloc[[i]].to_string()
                                        + "```") 
                                        for i in range(results.shape[0]-1) ]#reply_text(sess.get_results().to_string())
    else:
        update.message.reply_text("No discs found.")


def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


# Some helper functions for determining the input type, see set_schedule
def seconds(t: int) -> int:
    return t


def minutes(t: int) -> int:
    return t * 60


def hours(t: int) -> int:
    return minutes(t) * 60


def set_schedule(update: Update, context: CallbackContext) -> None:
    """Add a job to the queue."""
    options = {"s": seconds, "m": minutes, "h": hours}
    chat_id = update.message.chat_id
    try:
        # args[0] should contain the time for the timer in seconds
        input_list = list(str(context.args[0]))  # [0] value, [1] unit
        due = options[str(input_list[1])](int(input_list[0]))
        if due < 0:
            update.message.reply_text("Time must be non negative!")
            return

        job_removed = remove_job_if_exists(str(chat_id), context)
        context.job_queue.run_once(
            on_alarm, due, context=chat_id, name=str(chat_id)
        )

        text = "Update schedule successfully set!"
        if job_removed:
            text += " Existing one was removed."
        update.message.reply_text(text)
        logger.info(f'Timer set for: {context.args[0]}')

    except Exception as e:
        logger.exception(e)
        update.message.reply_text(
            "Usage: /set <seconds>s || <minutes>m || <hours>h "
        )


def get_details(update: Update, context: CallbackContext) -> None:
    found = sess.get_state()
    update.message.reply_text("Details from the discs found this far! \n")
    if found:
        details = sess.get_details()
        for name, inner in details.items():
            txt = '<pre>' + name + "\n" + pd.DataFrame(inner[0]).to_string() + '</pre>'
            update.message.reply_html(txt)
        return
    update.message.reply_text("Bad luck! Discs not found yet.")


def unset(update: Update, context: CallbackContext) -> None:
    """Remove the job if the user changed their mind."""
    chat_id = update.message.chat_id
    job_removed = remove_job_if_exists(str(chat_id), context)
    text = (
        "Cancelled automatic updates."
        if job_removed
        else "You have not set up an update schedule."
    )
    update.message.reply_text(text)


if __name__ == "__main__":
    state = OnState()
    sess = Scrape(URL, TARGETS, state)

    # init the bot and session
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # on different commands - answer in Telegram
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("targets", targets))
    dispatcher.add_handler(CommandHandler("update", updates))
    dispatcher.add_handler(CommandHandler("unset", unset))
    dispatcher.add_handler(CommandHandler("set", set_schedule))
    dispatcher.add_handler(CommandHandler("init", init_targets))
    dispatcher.add_handler(CommandHandler("add", add_targets))
    dispatcher.add_handler(CommandHandler("details", get_details))

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()
    """
    # Run until we have found the disc or keyboardinterrupt
    run = not sess.current_state() 
    while run:
        # Get updates from the page
        found = sess.update()
        
        if found:
            # Get the dataframe containing results
            df = sess.get_results()
            # Send alert via bot to user, containing information on the disc
            ...
            # 
        """
