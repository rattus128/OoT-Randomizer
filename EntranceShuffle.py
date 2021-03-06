import random
import logging
from State import State
from Rules import set_entrances_based_rules
from Entrance import Entrance


def get_entrance_pool(type):
    return {name: data for (name, data) in entrance_shuffle_table.items() if data[0] == type}


entrance_shuffle_table = {
    'Outside Deku Tree -> Deku Tree Lobby':                     ('Dungeon', { 'forward': 0x0000, 'return' : 0x0209, 'blue' : 0x0457 }),
    'Dodongos Cavern Entryway -> Dodongos Cavern Beginning':    ('Dungeon', { 'forward': 0x0004, 'return' : 0x0242, 'blue' : 0x047A }),
    'Zoras Fountain -> Jabu Jabus Belly Beginning':             ('Dungeon', { 'forward': 0x0028, 'return' : 0x0221, 'blue' : 0x010E }),
    'Sacred Forest Meadow -> Forest Temple Lobby':              ('Dungeon', { 'forward': 0x0169, 'return' : 0x0215, 'blue' : 0x0608 }),
    'Death Mountain Crater Central -> Fire Temple Lower':       ('Dungeon', { 'forward': 0x0165, 'return' : 0x024A, 'blue' : 0x0564 }),
    'Lake Hylia -> Water Temple Lobby':                         ('Dungeon', { 'forward': 0x0010, 'return' : 0x021D, 'blue' : 0x060C }),
    'Desert Colossus -> Spirit Temple Lobby':                   ('Dungeon', { 'forward': 0x0082, 'return' : 0x01E1, 'blue' : 0x0610 }),
    'Shadow Temple Warp Region -> Shadow Temple Entryway':      ('Dungeon', { 'forward': 0x0037, 'return' : 0x0205, 'blue' : 0x0580 }),
    'Kakariko Village -> Bottom of the Well':                   ('Dungeon', { 'forward': 0x0098, 'return' : 0x02A6, }),
    'Zoras Fountain -> Ice Cavern Beginning':                   ('Dungeon', { 'forward': 0x0088, 'return' : 0x03D4, }),
    'Gerudo Fortress -> Gerudo Training Grounds Lobby':         ('Dungeon', { 'forward': 0x0008, 'return' : 0x03A8, }),
}


class EntranceShuffleError(RuntimeError):
    pass


# Set entrances of all worlds, first initializing them to their default regions, then potentially shuffling part of them
def set_entrances(worlds):
    for world in worlds:
        world.initialize_entrances()

    if worlds[0].shuffle_dungeon_entrances:
        shuffle_entrances(worlds)

    set_entrances_based_rules(worlds)


# Shuffles entrances that need to be shuffled in all worlds
def shuffle_entrances(worlds):

    # Store all locations unreachable to differentiate which locations were already unreachable from those we made unreachable while shuffling entrances
    complete_itempool = [item for world in worlds for item in world.get_itempool_with_dungeon_items()]
    maximum_exploration_state_list = State.get_states_with_items([world.state for world in worlds], complete_itempool)

    all_locations = [location for world in worlds for location in world.get_locations()]
    already_unreachable_locations = [location for location in all_locations if not maximum_exploration_state_list[location.world.id].can_reach(location)]

    # Shuffle all entrance pools based on settings

    if worlds[0].shuffle_dungeon_entrances:
        dungeon_entrance_pool = get_entrance_pool('Dungeon')
        # The fill algorithm will already make sure gohma is reachable, however it can end up putting
        # a forest escape via the hands of spirit on Deku leading to Deku on spirit in logic. This is
        # not really a closed forest anymore, so specifically remove Deku Tree from closed forest.
        if (not worlds[0].open_forest):
            del dungeon_entrance_pool["Outside Deku Tree -> Deku Tree Lobby"]
        shuffle_entrance_pool(worlds, dungeon_entrance_pool, already_unreachable_locations)

    # Multiple checks after shuffling entrances to make sure everything went fine

    for world in worlds:
        entrances_shuffled = world.get_shuffled_entrances()

        # Check that all target regions have exactly one entrance among those we shuffled
        target_regions = [entrance.connected_region for entrance in entrances_shuffled]
        for region in target_regions:
            region_shuffled_entrances = list(filter(lambda entrance: entrance in entrances_shuffled, region.entrances))
            if len(region_shuffled_entrances) != 1:
                logging.getLogger('').error('%s has %d shuffled entrances after shuffling, expected exactly 1 [World %d]',
                                                region, len(region_shuffled_entrances), world.id)

    maximum_exploration_state_list = State.get_states_with_items([world.state for world in worlds], complete_itempool)

    # Log all locations unreachable due to shuffling entrances
    alr_compliant = True
    if not worlds[0].check_beatable_only:
        for location in all_locations:
            if not location in already_unreachable_locations and \
               not maximum_exploration_state_list[location.world.id].can_reach(location):
                logging.getLogger('').error('Location now unreachable after shuffling entrances: %s [World %d]', location, location.world.id)
                alr_compliant = False

    # Check for game beatability in all worlds
    if not State.can_beat_game(maximum_exploration_state_list):
        raise EntranceShuffleError('Cannot beat game!')

    # Throw an error if shuffling entrances broke the contract of ALR (All Locations Reachable)
    if not alr_compliant:
        raise EntranceShuffleError('ALR is enabled but not all locations are reachable!')


# Shuffle all entrances within a provided pool for all worlds
def shuffle_entrance_pool(worlds, entrance_pool, already_unreachable_locations):

    # Shuffle entrances only within their own world
    for world in worlds:

        # Initialize entrances to shuffle with their addresses and shuffle type
        entrances_to_shuffle = []
        for entrance_name, (type, addresses) in entrance_pool.items():
            entrance = world.get_entrance(entrance_name)
            entrance.type = type
            entrance.addresses = addresses
            # Regions should associate specific entrances with specific addresses. But for the moment, keep it simple as dungeon and
            # interior ER only ever has one rando entrance per region.
            if entrance.connected_region.addresses is not None:
                raise EntranceShuffleError('Entrance rando of regions with multiple rando entrances not supported [World %d]' % world.id)
            entrance.connected_region.addresses = addresses
            entrance.shuffled = True
            entrances_to_shuffle.append(entrance)

        # Split entrances between those that have requirements (restrictive) and those that do not (soft). These are primarly age requirements.
        # Restrictive entrances should be placed first while more regions are available. The remaining regions are then just placed on
        # soft entrances without any need for logic.
        restrictive_entrances, soft_entrances = split_entrances_by_requirements(worlds, entrances_to_shuffle)

        # Assumed Fill: Unplace, and assume we have access to entrances by connecting them to the root of reachability
        root = world.get_region("Links House")
        target_regions = [entrance.disconnect() for entrance in entrances_to_shuffle]
        target_entrances = []
        for target_region in target_regions:
            fill_entrance = Entrance("Root -> " + target_region.name, root)
            fill_entrance.connect(target_region)
            root.exits.append(fill_entrance)
            target_entrances.append(fill_entrance)

        shuffle_entrances_restrictive(worlds, restrictive_entrances, target_entrances, already_unreachable_locations)
        shuffle_entrances_fast(worlds, soft_entrances, target_entrances)


# Split entrances based on their requirements to figure out how each entrance should be handled when shuffling them
# This is done to ensure that we can place them in an order less likely to fail, and with the appropriate method to optimize the placement speed
# Indeed, some entrances should be handled before others, and this also allows us to determine which entrances don't need to check for reachability
# If all entrances were handled in a random order, the algorithm could have high chances to fail to connect the last few entrances because of requirements
def split_entrances_by_requirements(worlds, entrances_to_split):

    # Retrieve all items in the itempool, all worlds included
    complete_itempool = [item for world in worlds for item in world.get_itempool_with_dungeon_items()]

    # First, disconnect all entrances and save which regions they were originally connected to, so we can reconnect them later
    original_connected_regions = {}
    for entrance in entrances_to_split:
        original_connected_regions[entrance.name] = entrance.disconnect()

    # Generate the states with all entrances disconnected
    # This ensures that no pre exisiting entrances among those to shuffle are required in order for an entrance to be reachable as one age
    # Some entrances may not be reachable because of this, but this is fine as long as we deal with those entrances as being very limited
    maximum_exploration_state_list = State.get_states_with_items([world.state for world in worlds], complete_itempool)

    restrictive_entrances = []
    soft_entrances = []

    for entrance in entrances_to_split:
        # Here, we find entrances that may be unreachable under certain conditions
        if not maximum_exploration_state_list[entrance.world.id].can_reach(entrance, age='both'):
            restrictive_entrances.append(entrance)
            continue
        # If an entrance is reachable as both ages with all the other entrances disconnected,
        # then it will always be accessible as both ages no matter which combination of entrances we end up with.
        # Thus, those entrances aren't bound to any specific requirements and are very versatile
        soft_entrances.append(entrance)

    # Reconnect all entrances afterwards
    for entrance in entrances_to_split:
        entrance.connect(original_connected_regions[entrance.name])

    return restrictive_entrances, soft_entrances


# Shuffle entrances by connecting them to a region among the provided target regions list
# While shuffling entrances, the algorithm will use states generated from all items yet to be placed to figure how entrances can be placed
# If ALR is enabled, this will mean checking that all locations previously reachable are still reachable every time we try to place an entrance
# Otherwise, only the beatability of the game may be assured, which is what would be expected without ALR enabled
def shuffle_entrances_restrictive(worlds, entrances, target_entrances, already_unreachable_locations, retry_count=16):

    all_locations = [location for world in worlds for location in world.get_locations()]

    # Retrieve all items in the itempool, all worlds included
    complete_itempool = [item for world in worlds for item in world.get_itempool_with_dungeon_items()]

    maximum_exploration_state_list = []

    for _ in range(retry_count):
        success = True;
        random.shuffle(entrances)
        rollbacks = []

        for entrance in entrances:
            random.shuffle(target_entrances)

            for target in target_entrances:
                entrance.connect(target.disconnect())

                # Regenerate the states because the final states might have changed after connecting/disconnecting entrances
                # We also clear all state caches first because what was reachable before could now be unreachable and vice versa
                for maximum_exploration_state in maximum_exploration_state_list:
                    maximum_exploration_state.clear_cache()
                maximum_exploration_state_list = State.get_states_with_items([world.state for world in worlds], complete_itempool)

                # If we only have to check that the game is still beatable, and the game is indeed still beatable, we can use that region
                can_connect = True
                if not (worlds[0].check_beatable_only and State.can_beat_game(maximum_exploration_state_list)):

                    # Figure out if this entrance can be connected to the region being tested
                    # We consider that it can be connected if ALL locations previously reachable are still reachable
                    for location in all_locations:
                        if not location in already_unreachable_locations and \
                           not maximum_exploration_state_list[location.world.id].can_reach(location):
                            logging.getLogger('').debug('Failed to connect %s To %s (because of %s) [World %d]',
                                                            entrance, entrance.connected_region, location, entrance.world.id)

                            can_connect = False
                            break

                if can_connect:
                    rollbacks.append((target, entrance))
                    used_target = target
                    break

                # The entrance and target combo no good, undo and continue try the next
                target.connect(entrance.disconnect())

            if entrance.connected_region is None:
                # An entrance failed to place every remaining target. This attempt is a bust.
                success = False
                break

            target_entrances.remove(used_target)

        if success:
            for target, entrance in rollbacks:
                logging.getLogger('').debug('Connected %s To %s [World %d]', entrance, entrance.connected_region, entrance.world.id)
                target.parent_region.exits.remove(target)
                del target
            return

        for target, entrance in rollbacks:
            region = entrance.disconnect()
            target_entrances.append(region)
            target.connect(region)

        logging.getLogger('').debug('Entrance placement attempt failed [World %d]', entrances[0].world.id)

    raise EntranceShuffleError('Fill attempt retry count exceeded [World %d]' % entrances[0].world.id)

# Shuffle entrances by connecting them to a random region among the provided target regions list
# This doesn't check for reachability nor beatability and just connects all entrances to random regions
# This is only meant to be used to shuffle entrances that we already know as completely versatile
# Which means that they can't ever permanently prevent the access of any locations, no matter how they are placed
def shuffle_entrances_fast(worlds, entrances, target_entrances):

    random.shuffle(target_entrances)
    for entrance in entrances:
        target = target_entrances.pop()
        entrance.connect(target.disconnect())
        target.parent_region.exits.remove(target)
        del target
        logging.getLogger('').debug('Connected %s To %s [World %d]', entrance, entrance.connected_region, entrance.world.id)

