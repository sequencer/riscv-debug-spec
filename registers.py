#!/usr/bin/env python3

import sys
import xml.etree.ElementTree
import argparse
import sympy
from sympy.functions.elementary.miscellaneous import Max
import math
import re
import collections
from functools import cmp_to_key

class Registers( object ):
    def __init__( self, name, label, prefix, description, skip_index,
            skip_access, skip_reset, depth ):
        self.name = name
        self.label = label
        self.prefix = prefix or ""
        self.description = description
        self.skip_index = skip_index
        self.skip_access = skip_access
        self.skip_reset = skip_reset
        self.depth = depth
        self.registers = []

    def add_register( self, register ):
        self.registers.append( register )

def sympy_compare_lowBit( a, b ):
    if sympy.simplify("(%s) > (%s)" % ( a.lowBit, b.lowBit )) == True:
        return 1
    if sympy.simplify("(%s) < (%s)" % ( a.lowBit, b.lowBit )) == True:
        return -1
    return 0

class Register( object ):
    def __init__( self, name, short, description, address, sdesc, define ):
        self.name = name
        self.short = short
        self.description = description
        self.address = address
        self.sdesc = sdesc
        self.define = define
        self.fields = []

        self.label = ( short or name ).lower() # TODO: replace spaces etc.

    def add_field( self, field ):
        self.fields.append( field )
        self.fields.sort( key=cmp_to_key(sympy_compare_lowBit), reverse=True )

    def check( self ):
        previous = None
        for f in self.fields:
            if not previous is None:
                expression = "(%s) > (%s)" % ( previous, f.highBit )
                result = sympy.simplify( expression )
                if type( result ) == bool:
                    assert result, "%s in %s of %s" % ( expression, f, self )

                expression = "(%s) - (%s)" % ( previous, f.highBit )
                delta = sympy.simplify( expression )
                try:
                    delta = int( delta )
                    assert delta == 1, \
                            "%s doesn't have all bits defined above %s (%s)" % ( self, f, expression )
                except TypeError:
                    pass
            previous = f.lowBit
        assert previous is None or int( previous ) == 0, \
                "%s isn't defined down to 0 (%r)" % ( self, previous )

    def width( self ):
        if self.fields:
            return Max(*(f.highBit for f in self.fields))
        else:
            return 0

    def __str__( self ):
        return self.name

class Value( object ):
    def __init__( self, element ):
        self.value = element.get( 'v' )
        self.range = element.get( 'range' )
        if self.range:
            self.low, self.high = self.range.split( ":" )
        self.text = element.text.strip()
        self.tail = element.tail.strip()
        self.name = element.get( "name" )
        self.duplicate = element.get( "duplicate" )

    def to_latex( self ):
        result = []
        if self.range:
            result.append("%s--%s (%s): %s\n" % ( self.low, self.high, self.name, self.text ))
        else:
            result.append("%s (%s): %s\n" % ( self.value, self.name, self.text ))
        if self.tail:
            result.append( self.tail )
        return "\n".join( result )

    def to_c_definitions( self, prefix ):
        result = []
        name = "%s_%s" % ( prefix, toCIdentifier( self.name.upper() ))
        result.append(( "comment", "%s: %s" % ( self.name, self.text )))
        if self.range:
            result.append(( "%s_LOW" % name, self.low ))
            result.append(( "%s_HIGH" % name, self.high ))
        else:
            result.append(( name, self.value ))
        if self.tail:
            result.append(( "comment", self.tail ))
        return result

class Field( object ):
    def __init__( self, name, lowBit, highBit, reset, access, description,
            sdesc, define, values ):
        self.name = name
        self.lowBit = lowBit
        self.highBit = highBit
        self.reset = reset
        self.access = access
        self.description = description
        self.define = define
        self.values = values

        name_counts = collections.Counter( v.name for v in values if not v.duplicate )
        assert all( v == 1 for v in name_counts.values() ), \
            "Duplicate field name in field %s" % self.name

        value_counts = collections.Counter( v.value for v in values if not v.duplicate )
        assert all( v == 1 for v in value_counts.values() ), \
            "Duplicate field value in field %s" % self.name

    def length( self ):
        return sympy.simplify( "1 + (%s) - (%s)" % ( self.highBit, self.lowBit ) )

    def columnWidth( self ):
        text = str( self.length() )
        if text.isdigit():
            l = int( text )
        else:
            # Fancier would be to assume XLEN is 32 or something.
            l = 20
        return max( l, len( self.name ), len( self.lowBit + self.highBit ) * 1.2 )

    def latex_description(self):
        result = [self.description]
        for value in self.values:
            result.append(value.to_latex())
        return "\n\n".join(result)

    def __str__( self ):
        return self.name

def parse_bits( field ):
    """Return high, low (inclusive)."""
    text = field.get( 'bits' )
    parts = text.split( ':' )
    if len( parts ) == 1:
        return parts * 2
    elif len( parts ) == 2:
        return parts
    else:
        assert False, text

def parse_xml( path ):
    e = xml.etree.ElementTree.parse( path ).getroot()
    if e.text:
        description = e.text.strip()
    else:
        description = ""
    registers = Registers( e.get( 'name' ), e.get( 'label' ),
            e.get( 'prefix' ), description,
            int( e.get( 'skip_index', 0 ) ),
            int( e.get( 'skip_access', 0 ) ),
            int( e.get( 'skip_reset', 0 ) ),
            int( e.get( 'depth', 1 )))
    for r in e.findall( 'register' ):
        name = r.get( 'name' )
        short = r.get( 'short' )
        if r.text:
            description = r.text.strip()
        else:
            description = ""
        register = Register( name, short, description,
                r.get( 'address' ), r.get( 'sdesc' ),
                int( r.get( 'define', '1' ) ) )

        fields = r.findall( 'field' )
        for f in fields:
            highBit, lowBit = parse_bits( f )
            if f.text:
                description = f.text.strip()
            else:
                description = ""
            if f.get( 'name' ) == '0':
                define = int( f.get( 'define', '0' ) )
            else:
                define = int( f.get( 'define', '1' ) )
            values = [ Value( v ) for v in f.findall( 'value' ) ]
            field = Field( f.get( 'name' ), lowBit, highBit, f.get( 'reset' ),
                    f.get( 'access' ), description, f.get( 'sdesc' ),
                    define, values )
            register.add_field( field )

        register.check()
        registers.add_register( register )
    return registers

def toLatexIdentifier( *args ):
    replacements = (
            ( '/', '' ),
            ( '\\_', '' ),
            ( ' ', '' ),
            ( '-', '' ),
            ( '_', '' ),
            ( '(', '' ),
            ( ')', '' ),
            ( '64', 'Sixtyfour' ),
            ( '32', 'Thirtytwo' ),
            ( '28', 'Twentyeight' ),
            ( '16', 'Sixteen' ),
            ( '15', 'Fifteen' ),
            ( '11', 'Eleven' ),
            ( '9', 'Nine' ),
            ( '8', 'Eight' ),
            ( '7', 'Seven' ),
            ( '6', 'Six' ),
            ( '5', 'Five' ),
            ( '4', 'Four' ),
            ( '3', 'Three' ),
            ( '2', 'Two' ),
            ( '1', 'One' ),
            ( '0', 'Zero' )
            )
    text = ""
    for arg in args:
        arg = (arg or "").lower()
        for frm, to in replacements:
            arg = arg.replace( frm, to )
        if arg and text:
            arg = arg[0].upper() + arg[1:]
        text += arg
    return text

def toCIdentifier( text ):
    return re.sub( "[^\w]", "_", text )

def write_definitions( fd, registers ):
    for r in registers.registers:
        regid = r.short or r.label
        if r.define:
            macroName = toLatexIdentifier( registers.prefix, regid )
            fd.write( "\\defregname{\\R%s}{\\hyperref[%s]{%s}}\n" % (
                macroName, toLatexIdentifier( registers.prefix, r.label ), r.short or r.label ) )
        for f in r.fields:
            if f.define:
                fd.write( "\\deffieldname{\\F%s}{\\hyperref[%s]{%s}}\n" % (
                        toLatexIdentifier( registers.prefix, regid, f.name ),
                        toLatexIdentifier( registers.prefix, regid, f.name ),
                        f.name ) )

class Macro:
    def __init__(self, name, expressionText):
        self.name = name
        self.expression = sympy.simplify(expressionText)
        self.atoms = self.expression.atoms(sympy.Symbol)

    def prototype(self):
        if self.atoms:
            return "%s(%s)" % (self.name, ", ".join(str(a) for a in self.atoms))
        else:
            return self.name

    def body(self):
        return self.expression

def sympy_to_c(expression):
    """Implement our own string function, so we can replace 2** with 1<<."""
    if isinstance(expression, sympy.Number):
        if (expression >= 2**32):
            return "0x%xULL" % expression
        elif (expression >= 2**31):
            return "0x%xU" % expression
        elif (expression >= 10):
            return "0x%x" % expression
        elif (expression > -10):
            return "%d" % expression
        elif (expression > -2**31):
            return "-0x%x" % -expression
        elif (expression > -2**32):
            return "-0x%xU" % -expression
        else:
            return "-0x%xULL" % -expression
    elif isinstance(expression, sympy.Symbol):
        return str(expression)
    elif isinstance(expression, sympy.Add):
        return "(" + " + ".join(sympy_to_c(t) for t in reversed(expression.args)) + ")"
    elif isinstance(expression, sympy.Mul):
        return "(" + " * ".join(sympy_to_c(t) for t in expression.args) + ")"
    elif isinstance(expression, sympy.Pow):
        base, exponent = expression.as_base_exp()
        assert base == 2, "Power must have base of two, not %r" % base
        return "(1ULL<<%s)" % sympy_to_c(exponent)
    raise Exception("Unsupported sympy object %r of type %r" % (expression, type(expression)))

def write_cheader( fd, registers ):
    definitions = []
    for r in registers.registers:
        name = toCIdentifier( r.short or r.label ).upper()
        prefname = registers.prefix + name
        if r.define and not r.address is None:
            definitions.append((prefname, r.address))
        try:
            if r.width() <= 32:
                suffix = "U"
            else:
                suffix = "ULL"
        except TypeError:
            suffix = "ULL"
        for f in r.fields:
            if f.define:
                if f.description:
                    definitions.append(( "comment", f.description ))
                prefix = "%s_%s" % ( prefname, toCIdentifier( f.name ).upper() )
                offset = Macro(
                    "%s_OFFSET" % prefix,
                    f.lowBit
                )
                definitions.append(( offset.prototype(), offset.body() ))
                length = Macro(
                    "%s_LENGTH" % prefix,
                    f.length()
                )
                definitions.append(( length.prototype(), length.body() ))
                # sympy doesn't support a bit shift (<<) operator, so here we
                # use power (**) instead.
                mask = Macro(
                    prefix,
                    ((2 ** sympy.simplify(f.length())) - 1) * (2 ** sympy.simplify(f.lowBit))
                )
                definitions.append(( mask.prototype(), mask.body() ))

                for v in f.values:
                    definitions += v.to_c_definitions(prefix)

    counted = collections.Counter(name for name, value in definitions)
    for name, value in definitions:
        if name == "comment":
            fd.write( "/*\n" )
            for line in value.splitlines():
                fd.write( (" * %s" % line.strip()).rstrip() + "\n" )
            fd.write( " */\n" )
            continue
        if counted[name] == 1:
            if not isinstance(value, str):
                value = sympy_to_c(value)
            fd.write( "#define %-35s %s\n" % ( name, value ) )

def write_chisel( fd, registers ):
    fd.write("package freechips.rocketchip.devices.debug\n\n")
    fd.write("import chisel3._\n\n")

    fd.write("// This file was auto-generated from the repository at https://github.com/riscv/riscv-debug-spec.git,\n")
    fd.write("// 'make chisel'\n\n")

    fd.write("object " + registers.prefix + "RegAddrs {\n")

    for r in registers.registers:
        name = toCIdentifier( r.short or r.label ).upper()
        prefname = registers.prefix + name
        if (r.define and r.address):
            if r.description:
                fd.write ("  /* " + r.description + "\n  */\n")
            fd.write ("  def " + prefname + " =  "+ r.address + "\n\n")

    fd.write("}\n\n")

    for r in registers.registers:
        name = toCIdentifier( r.short or r.label ).upper()

        if (r.fields and r.define) :
            sorted_fields = sorted(r.fields, key = lambda x: int(x.lowBit), reverse = True)
            topbit = 31
            reserved = 0
            fd.write("class " + name + "Fields extends Bundle {\n\n")
            for f in sorted_fields:

                # These need try-catch blocks in the general case,
                # but for DM1 Registers it's fine.

                fieldlength = int(f.length())
                lowbit = int(f.lowBit)

                newtopbit = lowbit + fieldlength - 1

                if (newtopbit != topbit):
                    reservedwidth = topbit - newtopbit
                    print(reserved)
                    print(reservedwidth)
                    fd.write("  val reserved%d = UInt(%d.W)\n\n" % (reserved, reservedwidth))
                    reserved = reserved + 1
                if not f.define:
                    reservedwidth = fieldlength
                    fd.write("  val reserved%d = UInt(%d.W)\n\n" % (reserved, reservedwidth))
                    reserved = reserved + 1
                else:
                    if f.description:
                        fd.write("  /* " + f.description + "\n  */\n")

                    fd.write("  val " + toCIdentifier(f.name) + " = ")
                    if (int(fieldlength) > 1):
                        fd.write("UInt(%d.W)\n\n" % fieldlength)
                    else:
                        fd.write("Bool()\n\n")

                topbit = int(lowbit) - 1

            lastlowbit = int(sorted_fields[-1].lowBit)
            if (lastlowbit > 0 ):
                fd.write("  val reserved" + reserved + "= UInt(" + lastlowbit + ".W)\n")

            fd.write("}\n\n")

def address_value( address ):
    if type( address ) == str:
        try:
            return int( address, 0 )
        except ValueError:
            return address
    return address

def compare_address(a, b):
    try:
        return int(sympy.simplify("%s-(%s)" % (a, b)))
    except TypeError:
        return cmp(a, b)

def print_latex_index( registers ):
    print(registers.description)

    columns = [
        ("Address", "r"),
        ("Name", "l")]
    if any(r.sdesc for r in registers.registers):
        columns.append(("Description", "l"))
    columns.append(("Page", "l"))

    # Force this table HERE so that it doesn't get moved into the next section,
    # which will be the description of a register.
    print("   \\begin{longtable}{|%s|}" % "|".join(b for a, b in columns))
    print("      \\caption{%s \\label{%s}}\\\\" %
            (registers.name, toLatexIdentifier(registers.prefix, registers.label)))
    print("      \\hline")
    print("      %s \\\\" % (" & ".join(a for a, b in columns)))
    print("      \\hline")
    print("      \\endhead")

    print("      \\multicolumn{%d}{r}{\\textit{Continued on next page}} \\\\" %
            len(columns))
    print("      \\endfoot")
    print("      \\endlastfoot")
    for r in sorted( registers.registers,
            key=cmp_to_key(lambda a, b: compare_address(a.address, b.address))):
        if r.short and (r.fields or r.description):
            page = "\\pageref{%s}" % toLatexIdentifier(registers.prefix, r.short)
        else:
            page = ""
        if r.short:
            name = "%s ({\\tt %s})" % (r.name, r.short)
        else:
            name = r.name
        if r.sdesc:
            print("%s & %s & %s & %s \\\\" % ( r.address, name, r.sdesc, page ))
        else:
            print("%s & %s & %s \\\\" % ( r.address, name, page ))
    print("         \hline")
    print("   \end{longtable}")

def print_latex_custom( registers ):
    sub = "sub" * registers.depth
    for r in registers.registers:
        if not r.fields and not r.description:
            continue

        if r.short:
            if r.address:
                print("\\%ssection{%s ({\\tt %s}, at %s)}" % ( sub, r.name,
                        r.short, r.address ))
            else:
                print("\\%ssection{%s ({\\tt %s})}" % ( sub, r.name, r.short ))
            print("\index{%s}" % r.short)
        else:
            if r.address:
                print("\\%ssection{%s (at %s)}" % ( sub, r.name, r.address ))
            else:
                print("\\%ssection{%s}" % ( sub, r.name ))
            print("\index{%s}" % r.name)
        if r.label and r.define:
            print("\\label{%s}" % toLatexIdentifier(registers.prefix, r.label))
        print(r.description)
        print()

        if r.fields:
            if registers.prefix == "CSR_":
                if int(r.address, 0) >= 0xc00:
                    print("This CSR is read-only.")
                elif all(f.access in ('R', '0') for f in r.fields):
                    print("Writing this read/write CSR has no effect.")
                else:
                    print("This CSR is read/write.")
            elif all(f.access in ('R', '0') for f in r.fields):
                print("This entire register is read-only.")

            print("\\begin{center}")

            totalWidth = sum( ( 3 + f.columnWidth() ) for f in r.fields )
            split = int( math.ceil( totalWidth / 80. ) )
            fieldsPerSplit = int( math.ceil( float( len( r.fields ) ) / split ) )
            subRegisterFields = []
            for s in range( split ):
                subRegisterFields.append( r.fields[ s*fieldsPerSplit : (s+1)*fieldsPerSplit ] )

            for registerFields in subRegisterFields:
                tabularCols = ""
                for f in registerFields:
                    fieldLength = str( f.length() )
                    lowLen = float( len( f.lowBit ) )
                    highLen = float( len( f.highBit ) )
                    tabularCols += "p{%.1f ex}" % ( f.columnWidth() * highLen / ( lowLen + highLen ) )
                    tabularCols += "p{%.1f ex}" % ( f.columnWidth() * lowLen / ( lowLen + highLen ) )
                print("\\begin{tabular}{%s}" % tabularCols)

                first = True
                for f in registerFields:
                    if not first:
                        print("&")
                    first = False
                    if f.highBit == f.lowBit:
                        print("\\multicolumn{2}{c}{\\scriptsize %s}" % f.highBit)
                    else:
                        print("{\\scriptsize %s} &" % f.highBit)
                        print("\\multicolumn{1}{r}{\\scriptsize %s}" % f.lowBit)

                # The actual field names
                print("\\\\")
                print("         \hline")
                first = True
                for f in registerFields:
                    if first:
                        cols = "|c|"
                    else:
                        cols = "c|"
                        print("&")
                    first = False
                    print("\\multicolumn{2}{%s}{$|%s|$}" % ( cols, f.name ))
                print("\\\\")
                print("         \hline")

                # Size of each field in bits
                print(" & ".join( "\\multicolumn{2}{c}{\\scriptsize %s}" % f.length() for f in registerFields ))
                print("\\\\")

                print("   \\end{tabular}")

            print("\\end{center}")

        columns = [("l", "Field", lambda f: f.name)]
        columns += [("p{0.5\\textwidth}", "Description", lambda f: f.latex_description())]
        if not registers.skip_access:
            columns += [("c", "Access", lambda f: f.access)]
        if not registers.skip_reset:
            columns += [("l", "Reset", lambda f: f.reset)]

        if any( f.description for f in r.fields ):
            print("\\tabletail{\\hline \\multicolumn{%d}{|r|}" % len(columns))
            print("   {{Continued on next page}} \\\\ \\hline}")
            print("   \\begin{longtable}{|%s|}" % "|".join(c[0] for c in columns))

            print("   \\hline")
            print("   %s\\\\" % " & ".join(c[1] for c in columns))
            print("   \\hline")
            print("   \\endhead")

            print("   \\multicolumn{%d}{r}{\\textit{Continued on next page}} \\\\" % \
                    len(columns))
            print("   \\endfoot")
            print("   \\endlastfoot")

            for f in r.fields:
                if f.description or f.values:
                    print("\\label{%s}" % toLatexIdentifier(registers.prefix, r.short or r.label, f.name))
                    print("\\index{%s}" % f.name)
                    print("   |%s| &" % str(columns[0][2](f)), end=' ')
                    print("%s\\\\" % " & ".join(str(c[2](f)) for c in columns[1:]))
                    print("   \\hline")

            print("   \\end{longtable}")
        print()

def print_latex_register( registers ):
    print("%\\usepackage{register}")
    sub = "sub" * registers.depth
    for r in registers.registers:
        if not r.fields and not r.description:
            continue

        if r.short:
            print("\\%ssection{%s (%s)}" % ( sub, r.name, r.short ))
        else:
            print("\\%ssection{%s}" % ( sub, r.name ))
        print(r.description)

        if not r.fields:
            continue
        print("\\begin{register}{H}{%s}{%s}" % ( r.name, r.address ))
        print("   \\label{reg:%s}{}" % r.label)
        for f in r.fields:
            length = f.length()
            if length is None:
                # If we don't know the length, draw it as 10 bits.
                length = 10
            print("   \\regfield{%s}{%d}{%s}{{%s}}" % (
                    f.name, length, f.lowBit, f.reset ))

        print("   \\begin{regdesc}")
        print("      \\begin{reglist}")
        for f in r.fields:
            if f.description:
                print("      \\item[%s] (%s) %s" % ( f.name, f.access,
                        f.description ))
        print("      \\end{reglist}")
        print("   \\end{regdesc}")

        print("\\end{register}")
        print()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument( 'path' )
    parser.add_argument( '--register', action='store_true',
            help='Use the LaTeX register module. No support for symbolic bit '
            'start/end positions.' )
    parser.add_argument( '--custom', action='store_true',
            help='Use custom LaTeX.' )
    parser.add_argument( '--definitions',
            help='Write register style definitions to the named file.' )
    parser.add_argument( '--cheader',
            help='Write C #defines to the named file.' )
    parser.add_argument( '--chisel',
            help='Write Scala Classes to the named file.' )
    parsed = parser.parse_args()

    registers = parse_xml( parsed.path )
    if parsed.definitions:
        write_definitions( open( parsed.definitions, "w" ), registers )
    if parsed.cheader:
        write_cheader( open( parsed.cheader, "w" ), registers )
    if parsed.chisel:
        write_chisel( open( parsed.chisel, "w" ), registers )
    if not registers.skip_index:
        print_latex_index( registers )
    if parsed.register:
        assert(0)
        print_latex_register( registers )
    if parsed.custom:
        print_latex_custom( registers )

sys.exit( main() )
