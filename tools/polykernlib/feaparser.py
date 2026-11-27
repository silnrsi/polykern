'''feaLib parser with the PolyKern additions:

    pos polybase GLYPHS <polyboundary x y, x y, ...>;
    pos polybase GLYPHS <polyboundary NULL>;
    pos polymark GLYPHS <polyboundary x y, x y, ...>;
    pos polymark GLYPHS <polyboundary NULL>;

    conditionset NAME { lookup GPOS 10 1; wght 400 700; } NAME;
    variation TAG NAME replace { ... } TAG;
    variation TAG NAME replace LOOKUP LOOKUP ... { ... } TAG;
    variation TAG NAME { ... } else { ... } TAG;
'''

from fontTools.feaLib.error import FeatureLibError
from fontTools.feaLib.lexer import Lexer
from fontTools.feaLib.parser import Parser as _Parser

from . import feaast


class Parser(_Parser):
    ast = feaast

    def parse_position_(self, enumerated, vertical):
        if self.next_token_ in ("polybase", "polymark"):
            return self.parse_position_poly_(enumerated, vertical)
        return _Parser.parse_position_(self, enumerated, vertical)

    def parse_position_poly_(self, enumerated, vertical):
        location = self.cur_token_location_
        role = self.expect_name_()
        if enumerated:
            raise FeatureLibError(f'"enumerate" is not allowed with {role}', location)
        if vertical:
            raise FeatureLibError("PolyKern is for horizontal text only", location)
        glyphs = self.parse_glyphclass_(accept_glyphname=True)
        boundary = self.parse_polyboundary_()
        self.expect_symbol_(";")
        return self.ast.PolyKernPosStatement(role, glyphs, boundary, location=location)

    def parse_polyboundary_(self):
        '''<polyboundary NULL> or <polyboundary x y, x y, ...>'''
        self.expect_symbol_("<")
        self.expect_keyword_("polyboundary")
        location = self.cur_token_location_
        if self.next_token_ == "NULL":
            self.expect_keyword_("NULL")
            self.expect_symbol_(">")
            return self.ast.PolyBoundary(None, location=location)
        points = []
        while True:
            x = self.expect_number_()
            y = self.expect_number_()
            points.append((x, y))
            if self.next_token_ == ",":
                self.expect_symbol_(",")
                continue
            self.expect_symbol_(">")
            break
        return self.ast.PolyBoundary(points, location=location)

    def parse_conditionset_(self):
        '''As fontTools' parse_conditionset_, but also accepts lookup support tests:
        lookup GPOS|GSUB <lookup type> <subtable format>;'''
        location = self.cur_token_location_
        name = self.expect_name_()
        conditions = {}
        lookuptests = []
        self.expect_symbol_("{")
        while self.next_token_ != "}":
            self.advance_lexer_()
            if self.is_cur_keyword_("lookup"):
                tableLocation = self.cur_token_location_
                table = self.expect_name_()
                if table not in ("GPOS", "GSUB"):
                    raise FeatureLibError("Expected GPOS or GSUB", tableLocation)
                lookuptests.append((table, self.expect_number_(), self.expect_number_()))
                self.expect_symbol_(";")
                continue
            if self.cur_token_type_ is not Lexer.NAME:
                raise FeatureLibError("Expected an axis name", self.cur_token_location_)
            axis = self.cur_token_
            if axis in conditions:
                raise FeatureLibError(f"Repeated condition for axis {axis}",
                                      self.cur_token_location_)
            values = []
            for _ in range(2):
                if self.next_token_type_ is Lexer.FLOAT:
                    values.append(self.expect_float_())
                else:
                    values.append(self.expect_number_(variable=False))
            self.expect_symbol_(";")
            conditions[axis] = tuple(values)
        self.expect_symbol_("}")
        finalname = self.expect_name_()
        if finalname != name:
            raise FeatureLibError('Expected "%s"' % name, self.cur_token_location_)
        return self.ast.ConditionsetStatement(name, conditions, lookuptests, location=location)

    def parse_feature_block_(self, variation=False):
        '''As fontTools' parse_feature_block_, but a variation block may say "replace"
        after its condition set, optionally followed by the names of the lookups to
        replace, and may have an else block.'''
        if not variation:
            return _Parser.parse_feature_block_(self, variation)
        assert self.cur_token_ == "variation"
        location = self.cur_token_location_
        tag = self.expect_tag_()
        vertical = tag in {"vkrn", "vpal", "vhal", "valt"}
        stylisticset = tag if tag in self.SS_FEATURE_TAGS else None
        cv_feature = tag if tag in self.CV_FEATURE_TAGS else None
        size_feature = tag == "size"
        conditionset = self.expect_name_()
        replace = False
        replaceLookups = []
        if self.next_token_ == "replace":
            self.expect_keyword_("replace")
            replace = True
            while self.next_token_type_ is Lexer.NAME and self.next_token_ != "useExtension":
                name = self.expect_name_()
                lookup = self.lookups_.resolve(name)
                if lookup is None:
                    raise FeatureLibError(f'Unknown lookup "{name}"', self.cur_token_location_)
                replaceLookups.append(lookup)
        use_extension = False
        if self.next_token_ == "useExtension":
            self.expect_keyword_("useExtension")
            use_extension = True
        block = self.ast.VariationBlock(tag, conditionset, use_extension=use_extension,
                                        replace=replace, replaceLookups=replaceLookups,
                                        location=location)
        self.parse_block_(block, vertical, stylisticset, size_feature, cv_feature,
                          closing=False)
        if self.next_token_ == "else":
            self.expect_keyword_("else")
            if replace:
                raise FeatureLibError("A variation block cannot have both replace and else",
                                      self.cur_token_location_)
            block.elseBlock = self.ast.FeatureBlock(tag, use_extension=use_extension,
                                                    location=self.cur_token_location_)
            self.parse_block_(block.elseBlock, vertical, stylisticset, size_feature, cv_feature)
        else:
            self.parse_block_closing_(block)
        return block

    def parse_block_closing_(self, block):
        '''Reads "TAG ;" after the closing brace of a block.'''
        name = self.expect_name_()
        if name != block.name.strip():
            raise FeatureLibError('Expected "%s"' % block.name.strip(),
                                  self.cur_token_location_)
        self.expect_symbol_(";")

    def parse_block_(self, block, vertical, stylisticset=None, size_feature=False,
                     cv_feature=None, closing=True):
        '''A copy of fontTools' parse_block_, except that with closing false it stops after
        the closing brace, so that an else block can follow.'''
        self.expect_symbol_("{")
        for symtab in self.symbol_tables_:
            symtab.enter_scope()

        statements = block.statements
        while self.next_token_ != "}" or self.cur_comments_:
            self.advance_lexer_(comments=True)
            if self.cur_token_type_ is Lexer.COMMENT:
                statements.append(
                    self.ast.Comment(self.cur_token_, location=self.cur_token_location_))
            elif self.cur_token_type_ is Lexer.GLYPHCLASS:
                statements.append(self.parse_glyphclass_definition_())
            elif self.is_cur_keyword_("anchorDef"):
                statements.append(self.parse_anchordef_())
            elif self.is_cur_keyword_({"enum", "enumerate"}):
                statements.append(self.parse_enumerate_(vertical=vertical))
            elif self.is_cur_keyword_("feature"):
                statements.append(self.parse_feature_reference_())
            elif self.is_cur_keyword_("ignore"):
                statements.append(self.parse_ignore_())
            elif self.is_cur_keyword_("language"):
                statements.append(self.parse_language_())
            elif self.is_cur_keyword_("lookup"):
                statements.append(self.parse_lookup_(vertical))
            elif self.is_cur_keyword_("lookupflag"):
                statements.append(self.parse_lookupflag_())
            elif self.is_cur_keyword_("markClass"):
                statements.append(self.parse_markClass_())
            elif self.is_cur_keyword_({"pos", "position"}):
                statements.append(self.parse_position_(enumerated=False, vertical=vertical))
            elif self.is_cur_keyword_("script"):
                statements.append(self.parse_script_())
            elif self.is_cur_keyword_({"sub", "substitute", "rsub", "reversesub"}):
                statements.append(self.parse_substitute_())
            elif self.is_cur_keyword_("subtable"):
                statements.append(self.parse_subtable_())
            elif self.is_cur_keyword_("valueRecordDef"):
                statements.append(self.parse_valuerecord_definition_(vertical))
            elif stylisticset and self.is_cur_keyword_("featureNames"):
                statements.append(self.parse_featureNames_(stylisticset))
            elif cv_feature and self.is_cur_keyword_("cvParameters"):
                statements.append(self.parse_cvParameters_(cv_feature))
            elif size_feature and self.is_cur_keyword_("parameters"):
                statements.append(self.parse_size_parameters_())
            elif size_feature and self.is_cur_keyword_("sizemenuname"):
                statements.append(self.parse_size_menuname_())
            elif self.cur_token_type_ is Lexer.NAME and self.cur_token_ in self.extensions:
                statements.append(self.extensions[self.cur_token_](self))
            elif self.cur_token_ == ";":
                continue
            else:
                raise FeatureLibError(
                    "Expected glyph class definition or statement: got {} {}".format(
                        self.cur_token_type_, self.cur_token_),
                    self.cur_token_location_)

        self.expect_symbol_("}")
        for symtab in self.symbol_tables_:
            symtab.exit_scope()
        if closing:
            self.parse_block_closing_(block)
