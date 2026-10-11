/*
 * <one line to give the program's name and a brief idea of what it does.>
 *
 * Copyright (c) 2026.
 *         Copyright (C) <year>  <name of author>
 *
 *         This program is free software: you can redistribute it and/or modify
 *         it under the terms of the GNU Affero General Public License as
 *         published by the Free Software Foundation, either version 3 of the
 *         License, or (at your option) any later version.
 *
 *         This program is distributed in the hope that it will be useful,
 *         but WITHOUT ANY WARRANTY; without even the implied warranty of
 *         MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *         GNU Affero General Public License for more details.
 *
 *         You should have received a copy of the GNU Affero General Public License
 *         along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 */

import { useState } from "react";

export const useInitial = () => {
  const [status, setStatus] = useState({
    loading: false,
    error: false});
  /*
      Implement hook functionality here.
      If you need to execute async operation, set loading to true and when it's over, set loading to false.
      If you caught some errors, set error status to true.
      Initial hook is considered to be successfully completed if it will return {loading: false, error: false}.
    */
  return status;
};
