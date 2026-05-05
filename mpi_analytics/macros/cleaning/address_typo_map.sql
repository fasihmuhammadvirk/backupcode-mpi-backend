{% macro address_typo_map() %}
    {{
        return({
            "1054 Walton": ["1054walton"],
            "12 Rockwell": ["12 Rockwell Plbrooklyn, Ny 112"],
            "1281 Hoe Ave.": ["1281 Hoe Ave. LLC"],
            "128 Skillman": ["128skillman"],
            "161 Meserole Ave.": [ "161 Mesroele Ave."],
            "172-02 Hillside Ave.": ["172-02 Hilside Ave."],
            "200 Walworth St.": ["200 Walwort", "200 Walworth St.", "Deliver To 200 Walwoorth"],
            "225 Skillman St.": ["225 Skillman, LLC", "225 Skilman St, LLC", "225 Skilman St."],
            "233 Rutledge St.": ["233rutledge"],
            "260 East 72nd St.": ["260 E 72nd St."],
            "270 Nostrand Ave.": ["370nostranave"],
            "43 Gerry St.": ["43 Gerry Stbrooklyn, Ny 11206"],
            "54 Knoll St.": ["54 Noll St."],
            "618 Stage Rd.": ["618stagerd"],
            "806 East 170th St.": ["806 E170th St. Bronx, N Y10459", "806 E170th St. Bronx, North Y10459"],
            "291 Fenimore St.": ["291 Fenimore Sttree"],
        })
    }}
{% endmacro %}

