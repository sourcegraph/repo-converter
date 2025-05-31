# Import repo-converter modules
from utils.context import Context
from utils.logger import log



def start(ctx: Context) -> None:

    # Main application logic to iterate through the repos_to_convert_dict, and spawn sub processes, based on parallelism limits per server

    log(ctx, f"Repos to convert: {ctx.repos}", "info")

    return None
